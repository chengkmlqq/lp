"""ATP 资产「单模型测试」服务。

一次测试 = **分段执行 + 一份两边格式相同的对拍产物包**（``compare.json``）。

设计要点（对应需求：① 改完模型能在 Web 端直接测 ② 结果能直接跟 C# 端对比）：

1. **分段**：``materialize``（物化 + 引擎文件）→ ``geometry``（DAT→LIB）→
   ``simulate``（单次 ATP）。每段独立判定、可单独跑；判据看**产物**
   （文件哈希 / .lib 参数数值 / LIS 报错行），**不看退出码** —— ATP 退出码不可信
   （见 ``atp_geometry_pipeline._ensure_engine_files`` 注释：缺 graphics/startup 时
   不产出 .pch 但退出码仍为 0）。

2. **独立运行目录**（需求 ① 的关键）：
   - 运行目录 ``<engine_workdir>/atp-asset-test/<run_id>``
   - 引擎目录 ``D:\\ATP\\.runs\\t<run_id[:7]><场景短码>``（复用 ``_private_engine_dir``
     的短命名，保证 ``$INCLUDE`` 卡 ≤80 列）
   目录全新 ⇒ 没有 ``.geo_key_*`` / ``.gen_lib_*`` 几何指纹缓存 ⇒ **强制真重算**；
   同时不污染生产目录、并发不互相覆盖。

3. **复用生产函数**（不另写一套，否则测试绿 ≠ 生产能跑）：
   ``resolve_external_waveform_job`` / ``render_atp_template`` /
   ``_materialize_asset_files`` / ``_rewrite_includes`` / ``_private_engine_dir`` /
   ``compute_csharp_atp_params`` / ``regenerate_line_models`` / ``_build_command`` /
   ``_read_lis_flashover_detail``。测试模式只是「少跑几步 + 多存证据」。

4. **产出 compare.json**（schema ``lp.atp.compare/1``），字段与 C# harness 侧一致，
   可直接 diff。三层证据：文件 sha256（是否逐字节一致）+ .lib 参数级数值 + 业务数值。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import struct
import subprocess
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..models.atp_asset import AtpAsset, AtpAssetRun
from ..models.base import utcnow
from ..schemas.atp_asset import AtpAssetRunDetail, AtpAssetTestRunRequest

logger = logging.getLogger(__name__)

COMPARE_SCHEMA = "lp.atp.compare/1"
TEST_RUN_SUBDIR = "atp-asset-test"
STAGE_ORDER: tuple[str, ...] = ("materialize", "geometry", "simulate")
# 产物包要收集的文件（存在才收）
_ARTIFACT_SUFFIXES: tuple[str, ...] = (".dat", ".pch", ".lib", ".lis", ".pl4", ".atp", ".log")
# work.atp 的 $PARAMETER 段：``NAME=VALUE`` 赋值行（参数级对比用）
_NAMED_VALUE_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]{1,15})\s*=\s*([-+0-9.eE]+)\s*$")


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _artifact_entry(path: Path) -> dict[str, Any]:
    return {
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _parse_named_values(path: Path) -> dict[str, float]:
    """抽取 ``NAME=VALUE`` 赋值行（参数级数值对比用，比整文件哈希更鲁棒）。

    ⚠️ 指向的是 **work.atp 的 $PARAMETER 段**（如 ``RER001=14.``、``REHG______=40.17``），
    不是 .lib —— 实测 .lib 是 ``KARD/KARG/KBEG/KEND`` 头 + 位置制数值列，没有 NAME=VALUE。
    整文件 sha256 会因路径/文件名字符串差异产生假阳性，故以参数级数值为主判据。
    """
    if not path.is_file():
        return {}
    values: dict[str, float] = {}
    try:
        text = path.read_text(encoding="latin-1", errors="replace")
    except OSError:
        return {}
    for line in text.splitlines():
        match = _NAMED_VALUE_RE.match(line)
        if not match:
            continue
        name, raw = match.group(1), match.group(2)
        try:
            values[name] = float(raw)
        except ValueError:
            continue
    return values


def _lis_has_halt(path: Path) -> list[str]:
    """返回 LIS 里的致命行（``Halt in`` / ``KILL-code`` / ``error stop``）。"""
    if not path.is_file():
        return []
    hits: list[str] = []
    text = path.read_text(encoding="latin-1", errors="replace")
    for line in text.splitlines():
        upper = line.upper()
        if "HALT IN" in upper or "KILL-CODE" in upper or "ERROR STOP" in upper:
            hits.append(line.strip()[:200])
    return hits


def _normalize_stages(requested: Iterable[str] | None) -> list[str]:
    """把请求的段归一化，并补齐依赖（simulate 依赖 geometry 依赖 materialize）。"""
    items = [str(item).strip().lower() for item in (requested or []) if str(item).strip()]
    if not items or "all" in items:
        return list(STAGE_ORDER)
    unknown = [item for item in items if item not in STAGE_ORDER]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的测试阶段：{unknown}（可选 {list(STAGE_ORDER)} 或 all）",
        )
    last = max(STAGE_ORDER.index(item) for item in items)
    return list(STAGE_ORDER[: last + 1])


def _test_shim(run_id: str) -> SimpleNamespace:
    """给生产函数用的轻量 shim（它们只用 ``.id``）。

    8 字符（``t`` + run_id 前 7 位）与生产 ``snapshot.id[:8]`` 等长，
    保证 ``D:\\ATP\\.runs\\`` 之后的路径长度与生产一致（$INCLUDE 卡 ≤80 列）。
    """
    return SimpleNamespace(id=f"t{run_id[:7]}")


def _test_run_dir(run_id: str) -> Path:
    from .atp_asset_service import _resolve_engine_workdir

    path = _resolve_engine_workdir() / TEST_RUN_SUBDIR / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _test_engine_dir(*, run_id: str, resolved_job: Any) -> Path:
    from .fl_analysis_external import _private_engine_dir

    shim = _test_shim(run_id)
    engine_dir = _private_engine_dir(job=shim, snapshot=shim, resolved_job=resolved_job)
    engine_dir.mkdir(parents=True, exist_ok=True)
    return engine_dir


def _verdict(name: str, ok: bool, detail: str = "") -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail}


def _stage_result(
    stage: str,
    *,
    verdicts: list[dict[str, Any]],
    artifacts: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    log: str = "",
) -> dict[str, Any]:
    return {
        "stage": stage,
        "status": "ok" if all(item["ok"] for item in verdicts) else "failed",
        "verdicts": verdicts,
        "artifacts": artifacts or {},
        "metrics": metrics or {},
        "log": log,
    }


def _skipped_stage(stage: str, reason: str) -> dict[str, Any]:
    return {
        "stage": stage,
        "status": "skipped",
        "verdicts": [],
        "artifacts": {},
        "metrics": {},
        "log": reason,
    }


# ─────────────────────────────── 请求入口 ───────────────────────────────


def create_test_run(
    db: Session,
    *,
    asset_id: str,
    payload: AtpAssetTestRunRequest,
    actor_user_id: str | None,
) -> AtpAssetRunDetail:
    from .atp_asset_service import get_asset_by_id, get_run_by_id, serialize_run_detail

    asset = get_asset_by_id(db, asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ATP 资产不存在")
    stages = _normalize_stages(payload.stages)

    settings = get_settings()
    run = AtpAssetRun(
        asset_id=asset.id,
        status="pending",
        engine_mode=str(getattr(settings, "atp_engine_mode", "wine") or "wine"),
        runner_kind="atp",
        timeout_seconds=int(payload.timeout_seconds or 600),
        result_summary_json={
            "schema": COMPARE_SCHEMA,
            "kind": "atp_asset_test",
            "requested_stages": stages,
            "stages": {},
        },
        create_user=actor_user_id,
        update_user=actor_user_id,
    )
    db.add(run)
    db.flush()
    db.commit()

    payload_data = payload.model_dump(mode="json")
    try:
        task = _dispatch_test_run_task(
            run_id=run.id, payload_data=payload_data, actor_user_id=actor_user_id
        )
    except Exception as exc:  # pragma: no cover - 依赖 broker 可用性
        _mark_run_failed(
            db, run=run, actor_user_id=actor_user_id, reason=f"Celery dispatch failed: {exc}"
        )
        saved = get_run_by_id(db, run.id)
        if saved is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="测试运行记录保存失败"
            ) from exc
        return serialize_run_detail(saved)

    run.task_id = str(getattr(task, "id", "") or "") or None
    run.update_user = actor_user_id
    run.update_date = utcnow()
    db.commit()
    saved = get_run_by_id(db, run.id)
    if saved is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="测试运行记录保存失败"
        )
    return serialize_run_detail(saved)


def _dispatch_test_run_task(*, run_id: str, payload_data: dict[str, Any], actor_user_id: str | None):
    from ..tasks.atp_asset_tasks import execute_atp_asset_test_run_job

    return execute_atp_asset_test_run_job.delay(run_id, payload_data, actor_user_id)


def _mark_run_failed(
    db: Session, *, run: AtpAssetRun, actor_user_id: str | None, reason: str
) -> None:
    run.status = "failed"
    run.error_message = reason
    run.finished_at = utcnow()
    run.update_user = actor_user_id
    run.update_date = utcnow()
    db.commit()


# ─────────────────────────────── Worker 执行 ───────────────────────────────


def execute_test_run_job(
    *, run_id: str, payload_data: dict[str, Any], actor_user_id: str | None
) -> None:
    from ..core.database import SessionLocal
    from .atp_asset_service import get_run_by_id, serialize_run_detail
    from .fl_analysis_external import resolve_external_waveform_job

    db = SessionLocal()
    try:
        run = get_run_by_id(db, run_id)
        if run is None or run.status in {"success", "failed"}:
            return
        payload = AtpAssetTestRunRequest.model_validate(payload_data)
        stages = _normalize_stages(payload.stages)

        run.status = "running"
        run.started_at = utcnow()
        run.finished_at = None
        run.error_message = None
        run.duration_ms = None
        run.update_user = actor_user_id
        run.update_date = utcnow()
        db.commit()

        started_perf = time.perf_counter()
        try:
            resolved_job = resolve_external_waveform_job(
                db,
                external_adapter="atp",
                adapter_config_json={"asset_id": run.asset_id},
                tower_type=payload.tower_kind,
                line_voltage_kv=payload.voltage_kv,
                scene_type=payload.scene,
            )
        except Exception as exc:
            _mark_run_failed(
                db, run=run, actor_user_id=actor_user_id, reason=f"ATP 资产解析失败：{exc}"
            )
            return

        run.storage_mount_code = resolved_job.storage_mount_code
        run.storage_root_path = resolved_job.storage_root_path
        db.commit()

        run_dir = _test_run_dir(run.id)
        engine_dir = _test_engine_dir(run_id=run.id, resolved_job=resolved_job)
        run.working_dir = str(run_dir)
        run.materialized_root_path = str(engine_dir)
        db.commit()

        ctx = _TestContext(
            db=db,
            run_id=run.id,
            asset=run.asset,
            payload=payload,
            resolved_job=resolved_job,
            run_dir=run_dir,
            engine_dir=engine_dir,
            shim=_test_shim(run.id),
        )

        stage_results: dict[str, Any] = {}
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        failed_stage: str | None = None

        if payload.dry_run:
            planned = ctx.planned_commands()
            run.engine_command = "\n".join(" ".join(item) for item in planned)
            run.status = "success"
            run.exit_code = 0
            run.stdout_text = json.dumps(
                {
                    "dry_run": True,
                    "commands": [{"command": item} for item in planned],
                    "run_dir": str(run_dir),
                    "engine_dir": str(engine_dir),
                },
                ensure_ascii=False,
                indent=2,
            )
            run.stderr_text = ""
            run.duration_ms = 0
            run.finished_at = utcnow()
            run.result_summary_json = {
                "schema": COMPARE_SCHEMA,
                "kind": "atp_asset_test",
                "dry_run": True,
                "requested_stages": stages,
                "stages": {},
            }
            run.update_user = actor_user_id
            run.update_date = utcnow()
            db.commit()
            return

        try:
            for stage in stages:
                if failed_stage is not None:
                    stage_results[stage] = _skipped_stage(stage, f"前置阶段 {failed_stage} 失败")
                    continue
                if stage == "materialize":
                    result = ctx.stage_materialize()
                elif stage == "geometry":
                    result = ctx.stage_geometry()
                else:
                    result = ctx.stage_simulate()
                stage_results[stage] = result
                stdout_parts.append(f"[{stage}]\n{result.get('log') or ''}")
                if result.get("log"):
                    logger.info("[ATP测试] %s：%s", stage, result["log"].splitlines()[-1:])
                if result["status"] == "failed":
                    failed_stage = stage
        except Exception as exc:  # pragma: no cover - 兜底，避免 celery 任务静默
            logger.exception("[ATP测试] 执行异常 run=%s", run.id)
            stderr_parts.append(str(exc))
            run.error_message = str(exc)
            failed_stage = failed_stage or "exception"

        compare_payload = ctx.build_compare_payload(stage_results)
        compare_path = run_dir / "compare.json"
        compare_path.write_text(
            json.dumps(compare_payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        artifact_zip = _write_artifact_zip(run_dir=run_dir, engine_dir=engine_dir)

        run.engine_command = "\n".join(" ".join(item) for item in ctx.command_log)
        run.exit_code = ctx.last_exit_code
        run.stdout_text = "\n\n".join(part for part in stdout_parts if part).strip() or None
        run.stderr_text = "\n\n".join(part for part in stderr_parts if part).strip() or None
        run.duration_ms = max(int((time.perf_counter() - started_perf) * 1000), 0)
        run.finished_at = utcnow()
        run.status = "failed" if failed_stage else "success"
        if failed_stage and not run.error_message:
            run.error_message = f"测试阶段失败：{failed_stage}"
        run.output_manifest_json = {
            "artifact_zip": str(artifact_zip) if artifact_zip else None,
            "compare_json": str(compare_path),
            "run_dir": str(run_dir),
            "engine_dir": str(engine_dir),
            "files": compare_payload.get("artifacts_index") or [],
        }
        run.result_summary_json = {
            "schema": COMPARE_SCHEMA,
            "kind": "atp_asset_test",
            "requested_stages": stages,
            "failed_stage": failed_stage,
            "stages": stage_results,
            "compare": compare_payload,
        }
        run.update_user = actor_user_id
        run.update_date = utcnow()
        db.commit()
        logger.info(
            "[ATP测试] run=%s 完成：status=%s failed_stage=%s 用时=%sms",
            run.id,
            run.status,
            failed_stage,
            run.duration_ms,
        )
    finally:
        db.close()


# ─────────────────────────────── 上下文与阶段实现 ───────────────────────────────


class _TestContext:
    """一次测试运行的全部上下文（阶段之间共享解析结果与产物索引）。"""

    def __init__(
        self,
        *,
        db: Session,
        run_id: str,
        asset: AtpAsset,
        payload: AtpAssetTestRunRequest,
        resolved_job: Any,
        run_dir: Path,
        engine_dir: Path,
        shim: SimpleNamespace,
    ) -> None:
        self.db = db
        self.run_id = run_id
        self.asset = asset
        self.payload = payload
        self.resolved_job = resolved_job
        self.run_dir = run_dir
        self.engine_dir = engine_dir
        self.shim = shim
        self.command_log: list[list[str]] = []
        self.last_exit_code: int | None = None
        self.rendered_text: str = ""
        self.entry_path: Path = run_dir / resolved_job.entry_file
        self.execution_options: dict[str, Any] = self._build_execution_options()
        self._lis_flashover: dict[str, Any] = {}
        # 参数来源：template（无杆塔，用参数模板默认值）/ tower（用传入的杆塔数据）
        self.params_source: str = (
            "tower" if (payload.base_tower or payload.profile or payload.params_source == "tower") else "template"
        )
        self._params: dict[str, str] | None = None
        self.param_diagnostics: dict[str, Any] = {}
        # 无杆塔模式：用模板 context 默认值显式合成的几何（None = 未合成/不需要）
        self.synthetic_geometry: dict[str, Any] | None = None
        self._geom_defaults: dict[str, Any] | None = None
        self._effective_geometry_cache: tuple[dict[str, Any], dict[str, Any]] | None = None

    # ---- 无杆塔模式的几何补全（方案B：显式合成，禁止静默 fallback）----

    def _template_defaults(self) -> dict[str, Any]:
        """参数模板的 context 默认值（_common.json 顶层 defaults，DB 行可覆盖）。"""
        if self._geom_defaults is None:
            from .atp_param_config import get_rules

            rules = get_rules()
            self._geom_defaults = dict(getattr(rules, "defaults", None) or {}) if rules is not None else {}
        return self._geom_defaults

    def _synth_number(self, *names: str) -> float | None:
        defaults = self._template_defaults()
        for name in names:
            raw = defaults.get(name)
            if raw is None:
                continue
            try:
                return abs(float(raw))
            except (TypeError, ValueError):
                continue
        return None

    def effective_geometry(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """返回本次测试**实际使用**的 profile / base_tower。

        ``params_source == "template"``（无杆塔）时，``build_dat_values`` 需要的
        「避雷线左/右中距」在模板体系里没有承载槽位（各塔型 RELE09/RELE10 语义还不同），
        因此用模板 context 默认值（``lw_l_eff``/``lw_r_eff``）**显式合成**，并把合成内容
        记进 ``self.synthetic_geometry`` 供对拍产物标注。

        生产路径（tower 模式）原样返回，不做任何补全 —— 缺数据仍然显式报错。
        """
        if self._effective_geometry_cache is not None:
            return self._effective_geometry_cache
        profile = dict(self.payload.profile or {})
        base_tower = dict(self.payload.base_tower or {})
        if self.params_source != "template":
            self._effective_geometry_cache = (profile, base_tower)
            return self._effective_geometry_cache

        synth: dict[str, Any] = {}
        lw = profile.get("lightning_wire")
        if not (
            isinstance(lw, dict)
            and lw.get("left_mid_distance_m") is not None
            and lw.get("right_mid_distance_m") is not None
        ):
            left = self._synth_number("lw_l_eff", "lw_l")
            right = self._synth_number("lw_r_eff", "lw_r")
            if left is None or right is None:
                raise RuntimeError(
                    "无杆塔模式需要避雷线左/右中距，但参数模板未提供默认值"
                    "（defaults.lw_l_eff / lw_r_eff）。请补模板默认值，或在请求里显式传 "
                    "profile.lightning_wire.{left,right}_mid_distance_m。"
                )
            profile["lightning_wire"] = {
                "left_mid_distance_m": left,
                "right_mid_distance_m": right,
            }
            synth["lightning_wire"] = dict(profile["lightning_wire"])

        # 相中距 / 相高：⚠️ 2026-09-20 补（配合 atp_geometry_pipeline._spacing 的对拍修复）
        # C# 口径下 .dat 的相中距取**杆塔几何**（circuit_geometry_json[*].phase_spacing_m），
        # 无杆塔模式下该几何为空 → 必须用模板默认值显式合成；否则 _spacing 会回退到
        # RELE 槽位，而单回塔型的 RELE09/03 并非相中距 → .dat 几何错位。
        cg = base_tower.get("circuit_geometry_json")
        cg_ok = (
            isinstance(cg, dict)
            and isinstance((cg.get("I") or {}).get("phase_spacing_m"), dict)
            and (cg["I"]["phase_spacing_m"] or {}).get("upper") is not None
        )
        if not cg_ok:
            sp_u = self._synth_number("sp_u")
            sp_m = self._synth_number("sp_m")
            sp_l = self._synth_number("sp_l")
            if sp_u is None or sp_m is None or sp_l is None:
                raise RuntimeError(
                    "无杆塔模式需要相中距，但参数模板未提供默认值"
                    "（defaults.sp_u / sp_m / sp_l）。请补模板默认值，或在请求里显式传 "
                    "base_tower.circuit_geometry_json。"
                )
            entry: dict[str, Any] = {
                "phase_spacing_m": {"upper": sp_u, "middle": sp_m, "lower": sp_l},
            }
            h_u = self._synth_number("h_u")
            h_m = self._synth_number("h_m")
            h_l = self._synth_number("h_l")
            if h_u is not None and h_m is not None and h_l is not None:
                entry["phase_height_m"] = {"upper": h_u, "middle": h_m, "lower": h_l}
            base_tower["circuit_geometry_json"] = {
                k: {kk: (dict(vv) if isinstance(vv, dict) else vv) for kk, vv in entry.items()}
                for k in ("I", "II", "III", "IV")
            }
            synth["circuit_geometry_json"] = entry

        if synth:
            self.synthetic_geometry = {
                **synth,
                "source": "参数模板 context 默认值（无杆塔模式显式合成）",
            }
        self._effective_geometry_cache = (profile, base_tower)
        return self._effective_geometry_cache

    # ---- 参数（无杆塔测试的核心）----

    def _voltage_kv(self) -> Any:
        if self.payload.voltage_kv is not None:
            return self.payload.voltage_kv
        raw = (self.asset.voltage_level or "").strip()
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    def compute_params(self) -> dict[str, str]:
        """算出 work.atp 的 ``$PARAMETER`` 参数集。

        - ``tower``：走生产函数 ``compute_csharp_atp_params``（内含 config_db 配置路径）
        - ``template``：**无杆塔** —— 资产维度（塔型/电压）+ 参数模板默认值
          （``allow_defaults=True``）。模板不可用或缺默认值时**显式报错**，
          绝不静默回落成 "1." 占位（那样 ATP 照样跑完，但结果毫无物理意义）。
        """
        from .atp_param_config import compute_params_detailed_from_runtime, mode as mapping_mode
        from .fl_analysis_external import compute_csharp_atp_params

        if self.params_source == "tower":
            return compute_csharp_atp_params(
                base_tower=dict(self.payload.base_tower or {}),
                profile=dict(self.payload.profile or {}),
                execution_options=self.execution_options,
            )

        kind = str(self.payload.tower_kind or self.asset.tower_type or "").strip()
        detailed = compute_params_detailed_from_runtime(
            base_tower={"tower_type": kind, "line_voltage_kv": self._voltage_kv()},
            profile={},
            execution_options={**self.execution_options, "tower_kind": kind},
            allow_defaults=True,
        )
        if detailed is None:
            raise RuntimeError(
                f"参数模板不可用（ATP_MAPPING_MODE={mapping_mode()}：DB 无模板行且 JSON 映射缺失）。"
                "无杆塔测试必须由参数模板提供默认值；禁止静默回落到需要杆塔上下文的代码路径。"
            )
        self.param_diagnostics = {
            "chain": list(detailed.chain),
            "tower_kind": detailed.tower_kind,
            "defaults_applied": list(detailed.defaults_applied),
            "defaults_used": dict(detailed.defaults_used),
            "unresolved": {slot: list(names) for slot, names in detailed.unresolved.items()},
            # 参数溯源(2026-09-23 新增)：槽位 → 来源标签 / 最终格式化值。
            # sources 由解析器的 apply_slots 填写：规则名 / 继承 / 默认值 / 本级关闭 / 缺变量等，
            # 前端「参数溯源」抽屉据此展示每个参数到底来自模板、系统默认还是用户输入。
            "sources": dict(detailed.sources),
            "resolved": dict(detailed.values),
        }
        if detailed.unresolved and not self.payload.allow_incomplete_defaults:
            preview = "；".join(
                f"{slot} ← 缺 {'/'.join(names)}"
                for slot, names in list(detailed.unresolved.items())[:6]
            )
            raise RuntimeError(
                f"参数模板默认值不完整（{len(detailed.unresolved)} 个槽位取不到值）：{preview}。"
                "请补该塔型/电压的模板默认值；确要用不完整参数跑，请显式传 "
                "allow_incomplete_defaults=true（结果可能无物理意义）。"
            )
        return detailed.as_dict()

    def ensure_params(self) -> dict[str, str]:
        if self._params is None:
            self._params = self.compute_params()
        return self._params

    # ---- 参数与渲染 ----

    def _build_execution_options(self) -> dict[str, Any]:
        from .fl_analysis_external import _with_binary_search_current

        options: dict[str, Any] = dict(self.payload.execution_options or {})
        if self.payload.tower_kind:
            options.setdefault("tower_kind", self.payload.tower_kind)
        if self.payload.voltage_kv is not None:
            options.setdefault("line_voltage_kv", self.payload.voltage_kv)
        if self.payload.scene:
            options.setdefault("scene_type", self.payload.scene)
        # 固定雷电流：让「单次 ATP」有可比口径（C# 侧同值）
        if self.payload.current_ka is not None:
            options = _with_binary_search_current(options, current_ka=float(self.payload.current_ka))
        return options

    def _template_context(self) -> dict[str, Any]:
        return {
            "job": {
                "id": self.run_id,
                "job_name": f"ATP测试-{self.asset.code}",
                "job_type": "atp_asset_test",
                "external_adapter": "atp",
            },
            "snapshot": {
                "id": self.shim.id,
                "seq_no": 1,
                "tower_no": str(self.payload.tower_no or self.asset.tower_type or self.asset.code),
                "tower_model": self.asset.tower_type,
                "tower_type": self.payload.tower_kind or self.asset.tower_type,
                "longitude": None,
                "latitude": None,
                "altitude_m": None,
                "terrain": None,
            },
            "base_tower": dict(self.payload.base_tower or {}),
            "profile": dict(self.payload.profile or {}),
            "execution_options": self.execution_options,
            "workflow": {},
            "baseline_result": {},
        }

    def render(self) -> str:
        from .fl_analysis_external import (
            PLACEHOLDER_PATTERN,
            _looks_like_csharp_equality_template,
            render_atp_template,
            render_csharp_equality_template,
        )

        template_text = self.resolved_job.atp_text
        is_csharp_style = _looks_like_csharp_equality_template(template_text)
        if self.params_source == "template" and not is_csharp_style and PLACEHOLDER_PATTERN.search(template_text):
            # 占位符风格（{base_tower.xxx}）模板的参数来自杆塔上下文 → 无杆塔测试不适用。
            # 明确报错而不是渲染出空值（禁止静默）。
            raise RuntimeError(
                "该 work.atp 是占位符风格（{...}）模板，其参数来自杆塔上下文；"
                "无杆塔测试目前只支持 C# 等号风格（$PARAMETER 区 NAME=值）模板。"
                "如需测这类模型，请传 base_tower/profile（params_source=tower）。"
            )

        text = render_atp_template(
            template_text,
            context=self._template_context(),
            parameter_bindings=self.resolved_job.parameter_bindings,
        )
        if is_csharp_style:
            text = render_csharp_equality_template(
                text,
                base_tower=dict(self.payload.base_tower or {}),
                profile=dict(self.payload.profile or {}),
                execution_options=self.execution_options,
                # 无杆塔测试：直接用参数模板默认值算出的参数集，不再从空杆塔上下文计算
                params_override=self.ensure_params() if self.params_source == "template" else None,
            )
        return text

    def rewrite_includes(self, text: str) -> str:
        from .fl_analysis_external import _rewrite_includes

        return _rewrite_includes(
            text, job=self.shim, snapshot=self.shim, resolved_job=self.resolved_job
        )

    # ---- 命令构造 ----

    def _build_command(self, *, input_path: Path, relative: bool) -> list[str]:
        from .fl_analysis_external import _build_command

        target = input_path.name if relative else input_path
        return _build_command(
            adapter=self.resolved_job.adapter,
            input_path=target,
            extra_args=list(self.resolved_job.extra_args or []),
        )

    def planned_commands(self) -> list[list[str]]:
        entry = Path(self.resolved_job.entry_file)
        commands = [
            self._build_command(input_path=Path(f"{name}.dat"), relative=True)
            for name in ("long", "short", "dahao", "xiaohao")
        ]
        commands.append(self._build_command(input_path=entry, relative=True))
        return commands

    def _engine_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(self.resolved_job.environment or {})
        env.setdefault("XDG_RUNTIME_DIR", "/tmp/.xdg")
        return env

    def _prepare_wine_env(self) -> list[dict[str, Any]]:
        """Wine 运行环境准备（复刻生产 fl_analysis_external 的必需步骤）。

        缺 D: 映射或双层 ATP 自指链接时，ATP 打不开任何 $INCLUDE →
        `KILL-code error stop`、退出码仍为 0、不产出 work.lis（静默错误）。
        因此这里与生产一致：建不出来直接抛错，不降级。
        """
        verdicts: list[dict[str, Any]] = []
        atp_root = Path("/app/data/wine/ATP")
        if not atp_root.exists():
            # 非容器环境（如 Windows 本机跑单测）：跳过，标记为未执行
            verdicts.append(
                _verdict("wine_engine_root", True, f"{atp_root} 不存在，跳过 Wine 环境准备")
            )
            return verdicts

        wine_prefix = os.environ.get("WINEPREFIX") or str(Path(os.path.expanduser("~")) / ".wine")
        dosdevices = Path(wine_prefix) / "dosdevices"
        dosdevices.mkdir(parents=True, exist_ok=True)
        Path("/tmp").mkdir(parents=True, exist_ok=True)

        d_drive = dosdevices / "d:"
        if not d_drive.exists() or not d_drive.is_symlink():
            if d_drive.exists() or d_drive.is_symlink():
                d_drive.unlink()
            d_drive.symlink_to(atp_root)
        verdicts.append(_verdict("wine_d_drive", True, str(d_drive)))

        nested_atp = atp_root / "ATP"
        if nested_atp.is_symlink() and not nested_atp.exists():
            nested_atp.unlink()
        if nested_atp.exists() and not nested_atp.is_symlink():
            leftovers = list(nested_atp.iterdir())
            if leftovers:
                raise RuntimeError(
                    f"ATP 双层目录 {nested_atp} 是真实目录（含 {len(leftovers)} 项），"
                    f"应为指向 {atp_root} 的符号链接；否则 D:\\ATP\\... 的 $INCLUDE 会读到"
                    "陈旧模板几何且不报错。请清空该目录后重试。"
                )
            nested_atp.rmdir()
        if not nested_atp.exists():
            nested_atp.symlink_to(atp_root)
        verdicts.append(_verdict("wine_nested_atp", True, str(nested_atp)))

        startup_src = atp_root / "startup"
        startup_dst = self.run_dir / "startup"
        if startup_src.exists() and not startup_dst.exists():
            startup_dst.write_bytes(startup_src.read_bytes())
        verdicts.append(
            _verdict(
                "run_dir_startup",
                startup_dst.exists(),
                f"{startup_dst}（ATP 启动必需，缺失报 Halt in RFUNL1）",
            )
        )
        return verdicts

    def _engine_fingerprints(self) -> dict[str, Any]:
        from .atp_geometry_pipeline import _ENGINE_FILES, _ENGINE_SOURCES

        out: dict[str, Any] = {}
        for name in _ENGINE_FILES:
            path = self.engine_dir / name
            if path.is_file():
                out[name] = _sha256_file(path)
                continue
            for root in _ENGINE_SOURCES:
                candidate = Path(root) / name
                if candidate.is_file():
                    out[name] = _sha256_file(candidate)
                    break
        return out

    def apply_runtime_slots(self, text: str) -> tuple[str, list[str]]:
        """补 C# 在调 tpbig **之前**刷进 work.atp 的运行期槽位（对齐 C#）。

        C# `ThreadCompute5_work_atp()` → `Update_work_atp1(work.atp, mSet_WorkAtp_Feature, 0)`
        （ComputeLightningProtection.cs:6128）会在跑 ATP 前把运行期算出的值写回 work.atp；
        未跑过的资产保持模板原值（如 `11K0=.25`、`14XXSS=-120/-240`）
        ⇒ 「文件里的值不能当权威，公式才是权威」。详见 `atp_work_atp_slots`。

        目前补两个（对拍 C# 发现 LP 缺失）：
          · `11K0`  ← 耦合系数 k0（几何耦合系数，逐塔型不同）
          · `14XXSS*` ← 电角度 = 输入电角度 − 90（A/B/C = 该值 / −120 / −240）
        """
        from .atp_work_atp_slots import (
            coupling_k0,
            rewrite_coupling_k0,
            rewrite_electric_angle,
        )

        log: list[str] = []
        base = dict(self.payload.base_tower or {})
        prof = dict(self.payload.profile or {})
        layers = dict(prof.get("geometry_layers_json") or {})
        cg = dict(base.get("circuit_geometry_json") or {})
        layer = cg.get("I") or layers.get("I") or {}
        lw = cg.get("lightning_wire") or layers.get("lightning_wire") or {}
        kind = str(self.payload.tower_kind or base.get("tower_kind") or "").strip().lower()
        voltage = self.payload.voltage_kv or base.get("line_voltage_kv") or 0
        insul_mm = prof.get("insulator_length_m")
        insul_m = (float(insul_mm) / 1000.0) if insul_mm is not None else None

        k0 = coupling_k0(
            tower_kind=kind,
            voltage_kv=float(voltage),
            shield_wire_height_m=prof.get("shield_wire_height_m"),
            left_mid_distance_m=lw.get("left_mid_distance_m"),
            right_mid_distance_m=lw.get("right_mid_distance_m"),
            insulator_length_m=insul_m,
            phase_geometry=layer,
            is_dc=kind in ("zhiliu", "vzhiliu"),
            phase_sequence=[str(prof[f"phase_sequence_{i}"]) for i in range(1, 5)
                            if prof.get(f"phase_sequence_{i}")],
        )
        text, k_ok = rewrite_coupling_k0(text, k0)
        log.append(
            f"耦合系数 11K0 = {k0 if k0 is None else round(k0, 6)}"
            + ("（已写入）" if k_ok else "（未找到 11K0 槽位，未写入）")
        )

        angle = prof.get("angle_deg")
        if angle is None:
            angle = base.get("angle_deg")
        angle_val = float(angle) if angle is not None else 0.0
        text, a_ok = rewrite_electric_angle(text, angle_val)
        log.append(
            f"电角度 14XXSS = {angle_val - 90.0:.1f}/{angle_val - 210.0:.1f}/{angle_val - 330.0:.1f}"
            + ("（已写入）" if a_ok else "（未找到 14XXSS 槽位，未写入）")
        )
        return text, log

    # ---- 阶段 1：物化 + 引擎文件 ----

    def stage_materialize(self) -> dict[str, Any]:
        from .atp_geometry_pipeline import GEOMETRY_LOCK, _ensure_engine_files
        from .fl_analysis_external import _materialize_asset_files

        verdicts: list[dict[str, Any]] = []
        log_lines: list[str] = []

        self.rendered_text = self.rewrite_includes(self.render())
        self.rendered_text, slot_log = self.apply_runtime_slots(self.rendered_text)
        log_lines.extend(slot_log)
        self.entry_path.write_text(self.rendered_text, encoding="gbk", errors="replace")
        log_lines.append(f"已渲染 {self.entry_path.name}（{len(self.rendered_text)} 字节）")

        include_lines = [
            line.strip()
            for line in self.rendered_text.splitlines()
            if line.strip().upper().startswith("$INCLUDE")
        ]
        priv_win = f"D:\\ATP\\.runs\\{self.shim.id}"
        bad_includes = [line for line in include_lines if priv_win not in line]
        verdicts.append(
            _verdict(
                "include_rewritten",
                bool(include_lines) and not bad_includes,
                f"{len(include_lines)} 条 $INCLUDE，未重写 {len(bad_includes)} 条"
                + (f"：{bad_includes[:2]}" if bad_includes else ""),
            )
        )
        verdicts.append(
            _verdict(
                "entry_file_written",
                self.entry_path.is_file() and self.entry_path.stat().st_size > 0,
                str(self.entry_path),
            )
        )

        with GEOMETRY_LOCK:
            _materialize_asset_files(
                db=self.db,
                run_dir=self.run_dir,
                resolved_job=self.resolved_job,
                private_engine_dir=self.engine_dir,
            )
            try:
                _ensure_engine_files(self.engine_dir)
                engine_ok, engine_detail = True, str(self.engine_dir)
            except RuntimeError as exc:
                engine_ok, engine_detail = False, str(exc)

        verdicts.append(_verdict("engine_files", engine_ok, engine_detail))
        verdicts.extend(self._prepare_wine_env())

        if self.params_source == "tower":
            verdicts.append(
                _verdict(
                    "params_source",
                    True,
                    f"tower（传入杆塔数据：base_tower {len(self.payload.base_tower or {})} 字段 / "
                    f"profile {len(self.payload.profile or {})} 字段）",
                )
            )
        else:
            # 无杆塔：参数由「资产维度 + 参数模板默认值」算出；缺默认值会在这里抛错（禁止静默）
            params = self.ensure_params()
            diag = self.param_diagnostics
            verdicts.append(
                _verdict(
                    "params_source",
                    True,
                    f"template（无杆塔）：模板链 {' → '.join(diag.get('chain') or []) or '-'}；"
                    f"用默认值的上下文变量 {len(diag.get('defaults_applied') or [])} 个；"
                    f"解析出 {len(params)} 个参数",
                )
            )

        artifacts = {
            name: _artifact_entry(self.run_dir / name)
            for name in (self.entry_path.name,)
            if (self.run_dir / name).is_file()
        }
        artifacts.update(
            {
                name: _artifact_entry(self.engine_dir / name)
                for name in ("startup", "graphics")
                if (self.engine_dir / name).is_file()
            }
        )
        metrics = {
            "entry_bytes": self.entry_path.stat().st_size if self.entry_path.is_file() else 0,
            "include_count": len(include_lines),
            "run_dir": str(self.run_dir),
            "engine_dir": str(self.engine_dir),
            "engine_fingerprints": self._engine_fingerprints(),
        }
        return _stage_result(
            "materialize",
            verdicts=verdicts,
            artifacts=artifacts,
            metrics=metrics,
            log="\n".join(log_lines),
        )

    # ---- 阶段 2：DAT → LIB（几何 + LCC）----

    def stage_geometry(self) -> dict[str, Any]:
        from .atp_geometry_pipeline import GEOMETRY_LOCK, regenerate_line_models

        verdicts: list[dict[str, Any]] = []
        log_lines: list[str] = []
        dat_names = ("long", "short", "dahao", "xiaohao")

        before = {
            name: _sha256_file(self.engine_dir / f"{name}.lib") for name in dat_names
        }
        params = self.ensure_params()
        env = self._engine_env()
        profile, base_tower = self.effective_geometry()
        if self.synthetic_geometry:
            log_lines.append(f"无杆塔几何合成：{json.dumps(self.synthetic_geometry, ensure_ascii=False)}")
        # ⚠️ 这里不要再套 GEOMETRY_LOCK：regenerate_line_models 内部已经加锁，
        # 而 GEOMETRY_LOCK 是 threading.Lock（不可重入）→ 同线程二次获取会永久死锁
        # （2026-09-19 实测：geometry 段挂起、celery 子进程卡在 futex_wait）。
        processed = regenerate_line_models(
            engine_dir=self.engine_dir,
            tower_kind=str(self.payload.tower_kind or self.asset.tower_type or ""),
            voltage_kv=self.payload.voltage_kv,
            params=params,
            profile=profile,
            base_tower=base_tower,
            build_command=lambda *, input_path: self._build_command(
                # regenerate_line_models 传进来的已是相对名（Path("long.dat")），
                # 这里原样透传：ATP 会把绝对路径整串小写化 → 打不开（rc=3）。
                input_path=input_path,
                relative=False,
            ),
            env=env,
            timeout_seconds=int(self.payload.timeout_seconds or 600),
        )
        log_lines.append(f"几何重生成处理文件：{processed}")

        artifacts: dict[str, Any] = {}
        recomputed_any = False
        for name in dat_names:
            for suffix in ("dat", "pch", "lib", "lis"):
                path = self.engine_dir / f"{name}.{suffix}"
                if path.is_file():
                    artifacts[f"{name}.{suffix}"] = _artifact_entry(path)
            after_lib = _sha256_file(self.engine_dir / f"{name}.lib")
            changed = before[name] != after_lib
            recomputed_any = recomputed_any or changed
            verdicts.append(
                _verdict(
                    f"{name}_lib_present",
                    after_lib is not None,
                    f"{self.engine_dir / f'{name}.lib'}",
                )
            )
            verdicts.append(
                _verdict(
                    f"{name}_lib_recomputed",
                    changed,
                    "本次重算（哈希变化）" if changed else "哈希未变 —— 可能是几何未变（正常）或缓存命中（需排查）",
                )
            )
            halt = _lis_has_halt(self.engine_dir / f"{name}.lis")
            if (self.engine_dir / f"{name}.lis").is_file():
                verdicts.append(
                    _verdict(f"{name}_lcc_no_halt", not halt, "; ".join(halt) or "无 Halt/错误行")
                )

        verdicts.append(
            _verdict(
                "geometry_actually_recomputed",
                recomputed_any,
                "至少一个 .lib 发生变化" if recomputed_any else "四个 .lib 哈希全未变：几何未生效或指纹缓存命中",
            )
        )
        if self.params_source == "template":
            verdicts.append(
                _verdict(
                    "geometry_source",
                    True,
                    (
                        "无杆塔：避雷线中距由参数模板默认值显式合成 → "
                        f"{json.dumps(self.synthetic_geometry.get('lightning_wire'), ensure_ascii=False)}"
                        if self.synthetic_geometry
                        else "无杆塔：请求已显式提供避雷线中距（未合成）"
                    ),
                )
            )
        metrics = {
            "params_count": len(params),
            "params_sha256": _sha256_text(
                json.dumps(params, ensure_ascii=False, sort_keys=True)
            ),
            "processed": list(processed or []),
        }
        return _stage_result(
            "geometry",
            verdicts=verdicts,
            artifacts=artifacts,
            metrics=metrics,
            log="\n".join(log_lines),
        )

    # ---- 阶段 3：单次 ATP 主仿真 ----

    def stage_simulate(self) -> dict[str, Any]:
        from ..core.subprocess_heartbeat import run_with_heartbeat
        from .fl_analysis_external import _read_lis_flashover_detail

        verdicts: list[dict[str, Any]] = []
        log_lines: list[str] = []
        env = self._engine_env()

        if not self.entry_path.is_file():
            self.rendered_text = self.rewrite_includes(self.render())
            self.entry_path.write_text(self.rendered_text, encoding="gbk", errors="replace")
            log_lines.append(f"补渲染 {self.entry_path.name}")

        # ⚠️ 传相对文件名（cwd=run_dir）：ATP 会把命令行路径整串小写化，
        # 绝对路径含大写段时打不开 → Halt in SYSDEP（rc=3）。与生产一致。
        command = self._build_command(input_path=self.entry_path, relative=True)
        self.command_log.append(command)
        log_lines.append(f"执行命令：{' '.join(command)}（cwd={self.run_dir}）")

        try:
            result = run_with_heartbeat(
                command,
                cwd=str(self.run_dir),
                env=env,
                timeout=int(self.payload.timeout_seconds or 600),
                label=f"ATP 模型测试 {self.asset.code} 单次仿真",
            )
            self.last_exit_code = int(result.returncode)
            if result.stdout:
                log_lines.append(result.stdout[-2000:])
            if result.stderr:
                log_lines.append(result.stderr[-2000:])
        except subprocess.TimeoutExpired:
            self.last_exit_code = None
            verdicts.append(
                _verdict("simulate_finished", False, f"超时（{self.payload.timeout_seconds}s）")
            )
            return _stage_result(
                "simulate", verdicts=verdicts, metrics={}, log="\n".join(log_lines)
            )
        except OSError as exc:
            self.last_exit_code = None
            verdicts.append(_verdict("simulate_finished", False, f"OSError: {exc}"))
            return _stage_result(
                "simulate", verdicts=verdicts, metrics={}, log="\n".join(log_lines)
            )

        verdicts.append(
            _verdict(
                "simulate_finished",
                True,
                f"退出码 {self.last_exit_code}（注意：ATP 退出码不可信，以下按产物判定）",
            )
        )

        lis_path = self.run_dir / "work.lis"
        pl4_path = self.run_dir / "work.pl4"
        halt = _lis_has_halt(lis_path)
        verdicts.append(
            _verdict(
                "work_lis_no_halt",
                lis_path.is_file() and not halt,
                "; ".join(halt) or (str(lis_path) if lis_path.is_file() else "work.lis 未产出"),
            )
        )
        verdicts.append(
            _verdict(
                "work_pl4_nonempty",
                pl4_path.is_file() and pl4_path.stat().st_size > 0,
                f"{pl4_path.stat().st_size if pl4_path.is_file() else 0} 字节",
            )
        )

        phases: list[str] = []
        flashover: int | None = None
        try:
            detail = _read_lis_flashover_detail(self.run_dir)
            if detail is not None:
                flashover, phases = detail
        except Exception as exc:  # pragma: no cover - 解析异常不影响其它判据
            logger.warning("[ATP测试] work.lis 闪络解析失败：%s", exc)
        self._lis_flashover = {
            "flashover_count": flashover,
            "flashover_phases": phases,
            "current_ka": self.payload.current_ka,
        }
        verdicts.append(
            _verdict(
                "flashover_parsed",
                flashover is not None,
                f"闪络相数={flashover}，相={','.join(phases) or '-'}"
                if flashover is not None
                else "work.lis 无 Close switch 信息（闪络判据取不到值）",
            )
        )

        artifacts = {
            name: _artifact_entry(self.run_dir / name)
            for name in ("work.lis", "work.pl4", self.entry_path.name)
            if (self.run_dir / name).is_file()
        }
        metrics = {
            "exit_code": self.last_exit_code,
            "current_ka": self.payload.current_ka,
            "flashover_count": flashover,
            "flashover_phases": phases,
            "lis_bytes": lis_path.stat().st_size if lis_path.is_file() else 0,
            "pl4_bytes": pl4_path.stat().st_size if pl4_path.is_file() else 0,
        }
        return _stage_result(
            "simulate", verdicts=verdicts, artifacts=artifacts, metrics=metrics, log="\n".join(log_lines)
        )

    # ---- 对拍产物 ----

    def build_compare_payload(self, stage_results: dict[str, Any]) -> dict[str, Any]:
        # 参数级对比（**主判据**）：Web 端渲染出的 work.atp $PARAMETER 段（NAME=VALUE）
        atp_params = _parse_named_values(self.entry_path)
        # 严格对比（附加）：四段 .lib 的 sha256（逐字节一致才算几何完全一致）
        lib_hashes: dict[str, Any] = {}
        for name in ("long", "short", "dahao", "xiaohao"):
            digest = _sha256_file(self.engine_dir / f"{name}.lib")
            if digest:
                lib_hashes[f"{name}.lib"] = digest
        artifacts_index: list[dict[str, Any]] = []
        for stage in stage_results.values():
            artifacts_index.extend((stage.get("artifacts") or {}).values())
        return {
            "schema": COMPARE_SCHEMA,
            "side": "web",
            "kind": "atp_asset_test",
            "run_id": self.run_id,
            "case": {
                "asset_code": self.asset.code,
                "asset_name": self.asset.name,
                "tower_type": self.payload.tower_kind or self.asset.tower_type,
                "voltage_kv": self.payload.voltage_kv,
                "scene": self.payload.scene,
                "entry_file": self.resolved_job.entry_file,
                "storage_root_path": self.resolved_job.storage_root_path,
                # 与 C# harness 原样对照的输入串（同一份输入 → 可比）
                "params_raw": self.payload.params_raw,
                "base_tower": dict(self.payload.base_tower or {}),
                "profile": dict(self.payload.profile or {}),
                "execution_options": {
                    key: value
                    for key, value in self.execution_options.items()
                    if key != "_run_subdir"
                },
            },
            "env": {
                "solver_host": "wine",
                "engine_mode": self.resolved_job.adapter,
                "engine_fingerprints": self._engine_fingerprints(),
                "run_dir": str(self.run_dir),
                "engine_dir": str(self.engine_dir),
            },
            "stages": stage_results,
            "params_source": self.params_source,
            "params_diagnostics": self.param_diagnostics,
            # 无杆塔模式下用模板默认值显式合成的几何（None = 未合成）；对拍时须注意
            "synthetic_geometry": self.synthetic_geometry,
            "atp_params": atp_params,
            "lib_hashes": lib_hashes,
            "simulate": dict(self._lis_flashover or {}),
            "artifacts_index": artifacts_index,
        }


def _write_artifact_zip(*, run_dir: Path, engine_dir: Path) -> Path | None:
    """把运行目录 + 引擎目录的相关产物打成 zip（供下载/离线对比）。"""
    target = run_dir / "artifacts.zip"
    members: list[tuple[Path, str]] = []
    for path in sorted(run_dir.iterdir()):
        if path.is_file() and path.name != target.name:
            members.append((path, path.name))
    for path in sorted(engine_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in _ARTIFACT_SUFFIXES:
            members.append((path, f"engine/{path.name}"))
    if not members:
        return None
    try:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, arcname in members:
                archive.write(path, arcname)
    except OSError as exc:  # pragma: no cover - 磁盘满等
        logger.warning("[ATP测试] 产物打包失败：%s", exc)
        return None
    return target


def read_artifact_zip(db: Session, *, run_id: str) -> tuple[Path, str]:
    """给下载接口用：返回 (zip 路径, 文件名)。"""
    from .atp_asset_service import get_run_by_id

    run = get_run_by_id(db, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试运行记录不存在")
    manifest = run.output_manifest_json or {}
    raw = manifest.get("artifact_zip")
    path = Path(str(raw)) if raw else None
    if path is None or not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="该运行没有产物包（可能仍在执行或已清理）"
        )
    return path, f"atp-test-{run.id}.zip"


def read_compare_json(db: Session, *, run_id: str) -> dict[str, Any]:
    """给对比接口用：返回 compare.json（与 C# harness 同 schema）。"""
    from .atp_asset_service import get_run_by_id

    run = get_run_by_id(db, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试运行记录不存在")
    summary = run.result_summary_json or {}
    compare = summary.get("compare")
    if not compare:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="该运行还没有对比产物（可能仍在执行）"
        )
    return compare


def cleanup_test_run_dir(run_id: str, *, keep: bool = False) -> None:
    """清理测试运行目录（默认保留；磁盘吃紧时可调用）。"""
    if keep:
        return
    run_dir = _test_run_dir(run_id)
    if run_dir.is_dir():
        shutil.rmtree(run_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 产物查看:文件内容读取 + pl4 波形解析(供测试抽屉「查看产物」用)
# ---------------------------------------------------------------------------

_MAX_ARTIFACT_TEXT_BYTES = 2 * 1024 * 1024
_PL4_HEAD_BYTES = 19 + 28  # 日期(19) + 7 个 uint32


def _candidate_artifact_paths(db: Session, run_id: str, rel: str) -> list[Path]:
    """候选产物路径:运行目录(work.*) + 引擎目录(.runs/*)。"""
    from .atp_asset_service import get_run_by_id

    run = get_run_by_id(db, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试运行记录不存在")
    candidates: list[Path] = []
    if run.working_dir:
        candidates.append(Path(run.working_dir) / rel)
    if run.materialized_root_path:
        candidates.append(Path(run.materialized_root_path) / rel)
    return [c for c in candidates if c.is_file()]


def read_test_run_file_content(
    db: Session, *, run_id: str, path: str
) -> dict[str, Any]:
    """读取测试运行产物文本内容(.lib/.dat/.lis/.pch/.log 等)。

    返回: ``{content_type: text|binary|not-found, content, preview_lines, size}``
    """
    rel = str(path or "").strip().lstrip("/")
    if not rel or ".." in rel.split("/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid path")
    candidates = _candidate_artifact_paths(db, run_id, rel)
    if not candidates:
        return {"content_type": "not-found", "content": "", "preview_lines": [], "size": 0}
    raw = candidates[0].read_bytes()
    try:
        # LIS/LOG 是文本但可能夹带个别非 UTF-8 字节(引擎输出),用 replace 兜底
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        return {
            "content_type": "binary",
            "content": "",
            "preview_lines": [],
            "size": len(raw),
        }
    lines = text.splitlines()
    preview = [line for line in lines[:500] if len(line) <= 2000]
    if len(raw) <= _MAX_ARTIFACT_TEXT_BYTES:
        return {
            "content_type": "text",
            "content": text,
            "preview_lines": preview,
            "size": len(raw),
        }
    return {
        "content_type": "text",
        "content": "",
        "preview_lines": preview,
        "size": len(raw),
    }


def parse_test_run_waveform(
    db: Session, *, run_id: str, max_points: int = 2000
) -> dict[str, Any]:
    """解析 work.pl4(ATP 二进制波形)为前端可画图的结构化数据。

    头部布局(与 ``fl_analysis_external._read_pl4_flashover_count`` 同一约定):
      偏移 19 起 7 个 uint32 LE: N_node, N_vol*2, N_all*2, N_tacs, N_zero,
      N_begin, N_end
    通道名区: 偏移 155 起每 18B 一个通道名(15B 名 + 3B 单位)。
    数据区: N_begin 起每步 (N_all+1)*4 字节, 第 1 个 float32 是时间,
      随后 N_all 个通道 float32。
    """
    from .atp_asset_service import get_run_by_id

    run = get_run_by_id(db, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试运行记录不存在")
    pl4_path = None
    for base in (run.working_dir, run.materialized_root_path):
        if base:
            cand = Path(base) / "work.pl4"
            if cand.is_file() and cand.stat().st_size > _PL4_HEAD_BYTES:
                pl4_path = cand
                break
    if pl4_path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该运行没有 work.pl4(波形未生成,可能 ATP 未跑出结果)",
        )
    data = pl4_path.read_bytes()

    def u32(offset: int) -> int:
        return int.from_bytes(data[offset : offset + 4], "little", signed=False)

    N_node = u32(19)
    N_all = u32(19 + 8) // 2
    N_begin = u32(19 + 20)
    N_end = u32(19 + 24)
    if N_node > 500 or N_all < 1 or N_all > 200:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"work.pl4 头部异常(N_node={N_node}, N_all={N_all})",
        )
    step_bytes = (N_all + 1) * 4
    if step_bytes <= 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="work.pl4 步长异常")
    N_N = (N_end - N_begin) // step_bytes
    if N_N <= 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="work.pl4 无数据点")

    # 通道名: 偏移 155 起每 18B(前 6 块 108B 是 ATP 固定诊断文本)
    names: list[str] = []
    units: list[str] = []
    name_off = 155
    for i in range(N_all):
        off = name_off + i * 18
        if off + 18 > len(data):
            break
        blk = data[off : off + 18]
        name = blk[:15].split(b"\x00")[0].decode("ascii", errors="replace").strip()
        unit = blk[15:18].split(b"\x00")[0].decode("ascii", errors="replace").strip()
        names.append(name or f"CH{i + 1}")
        units.append(unit)
    while len(names) < N_all:
        names.append(f"CH{len(names) + 1}")
        units.append("")

    # 时间列 + 各通道采样(降采样到 max_points)
    total = N_N
    if total > max_points:
        stride = total // max_points
    else:
        stride = 1
    picked = list(range(0, total, stride))
    if picked[-1] != total - 1:
        picked.append(total - 1)

    time_vals: list[float] = []
    ch_vals: list[list[float]] = [[] for _ in range(N_all)]
    for idx in picked:
        base = N_begin - 1 + idx * step_bytes
        if base + step_bytes > len(data):
            break
        time_vals.append(struct.unpack("<f", data[base : base + 4])[0])
        for c in range(N_all):
            off = base + 4 + c * 4
            ch_vals[c].append(struct.unpack("<f", data[off : off + 4])[0])

    return {
        "run_id": run_id,
        "channels": [
            {"name": names[i], "unit": units[i]} for i in range(N_all)
        ],
        "time": time_vals,
        "values": ch_vals,
        "sample_count": total,
        "downsampled_count": len(time_vals),
        "file_size": len(data),
    }
