from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import select, func as sa_func
from sqlalchemy.orm import Session

from ..core.celery_app import celery_app
from ..core.database import SessionLocal
from ..models.line import Line
from ..models.line_tower import LineTower
from ..models.lightning_amplitude import LightningAmplitude
from ..models.lightning_distribution import LightningDistribution


# ---------------------------------------------------------------------------
# 电压等级 -> 分组参数映射
# ---------------------------------------------------------------------------
def _resolve_params_for_voltage(voltage_kv: int | None) -> tuple[int, float, int]:
    """
    根据电压等级返回 (group_size, radius_km, num4).
    对应桌面版 banjin 逻辑：
      35/66/110kV → num2=1, banjin1, group_size=2, radius=1km, num4=2
      220/330kV   → num2=2, banjin2, group_size=3, radius=2km, num4=3
      500~1000kV  → num2=3, banjin3, group_size=5, radius=3km, num4=5
    """
    if voltage_kv is None:
        return 2, 1.0, 2  # 默认最小
    v = int(voltage_kv)
    if v <= 110:
        return 2, 1.0, 2
    elif v <= 330:
        return 3, 2.0, 3
    else:
        return 5, 3.0, 5


_DEGREE_TO_KM = 111.32


def _safe_km_per_lon(lat: float) -> float:
    """在给定纬度上，1°经度大约多少公里"""
    return _DEGREE_TO_KM * math.cos(math.radians(lat))


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """返回两点之间的大圆距离（公里）"""
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return 2 * 6371.0 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _compute_ng_per_group(
    groups: list[dict[str, Any]],
    lightning_strikes: list[dict[str, Any]],
    data_years: float,
    radius_km: float,
) -> dict[int, float]:
    """
    简化版 Ng 计算：最近邻分配 + 圆形缓冲区面积。
    每条落雷分配到最近的组中心，组面积 = π * radius_km²。
    与精确 Voronoi 相比有轻微误差，但工程可用。
    """
    if not groups or not lightning_strikes or data_years <= 0:
        return {}

    group_centers = {
        g["group_id"]: (g["center_lat"], g["center_lon"])
        for g in groups
    }
    area_km2 = math.pi * (radius_km ** 2)
    count_per_group: dict[int, int] = defaultdict(int)

    for strike in lightning_strikes:
        slat = strike["lat"]
        slon = strike["lon"]
        if slat is None or slon is None:
            continue

        best_id = min(
            group_centers,
            key=lambda gid: _haversine_km(
                slat, slon, group_centers[gid][0], group_centers[gid][1]
            ),
        )
        count_per_group[best_id] += 1

    return {
        gid: count / (area_km2 * data_years)
        for gid, count in count_per_group.items()
    }


# ---------------------------------------------------------------------------
# Celery 任务
# ---------------------------------------------------------------------------
def _capture(task_id: str, text: str) -> None:
    """写入 TaskLogCapture 缓冲（实时流 + 终态 MinIO 日志的权威来源）。"""
    try:
        from ..core.task_log_capture import TaskLogCapture

        buffer = TaskLogCapture.get(task_id)
        if buffer is not None:
            buffer.write(text)
    except Exception:
        pass


def _append_log(log_parts: list[str], task_id: str, text: str) -> None:
    """追加业务日志：写内存 log_parts（兼容旧 _upload_log 兜底）+ 同时写入采集器。"""
    log_parts.append(text)
    _capture(task_id, text)


def _upload_log(task_id: str, log_parts: list[str]) -> None:
    """上传任务日志（非致命错误，capture 为权威，此处保留为兜底）"""
    try:
        from ..services.task_log_service import upload_task_log

        upload_task_log(task_id, "\n".join(log_parts))
    except Exception:
        pass


@celery_app.task(
    name="app.tasks.lightning_tasks.import_lightning_distribution_job",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    acks_late=True,
)
def import_lightning_distribution_job(
    self,
    distribution_id: str,
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    """
    地闪分布导入一条龙任务（含出图）。

    Steps:
      1) 按 id 取 LightningDistribution，status=processing / stage=parsing
      2) 从 MinIO 下载 source_object_key → 字节流
      3) 逐行解析 "纬度 经度 电流"（stage=validating），累计 warning
      4) 基于内存落雷集合做统计（stage=statistics），结果写入 LightningDistribution
      5) stage=rendering：matplotlib 渲染密度图 PNG → 上传 MinIO → image_object_key
      6) status=completed（失败 → status=failed + error_message）

    不再向任何明细表 INSERT 落雷数据。
    """
    task_id = self.request.id
    log_parts: list[str] = [f"[{task_id}] Starting distribution import: {distribution_id}"]

    db: Session = SessionLocal()
    try:
        from ..services import minio_storage
        from ..services import lightning_statistics

        dist = db.execute(
            select(LightningDistribution).where(LightningDistribution.id == distribution_id)
        ).scalar_one_or_none()
        if not dist:
            _append_log(log_parts, task_id, f"[{task_id}] Distribution {distribution_id} not found, aborting")
            _upload_log(task_id, log_parts)
            return {"status": "failed", "error": "distribution not found"}

        dist.status = "processing"
        dist.stage = "parsing"
        dist.progress = 5
        dist.task_id = task_id
        db.commit()
        _append_log(log_parts, task_id, f"[{task_id}] source_object_key={dist.source_object_key}")

        # ---- 2. 从 MinIO 下载原始文件 ----
        content = minio_storage.get_object(dist.source_object_key)
        text = lightning_statistics.decode_text_bytes(content)
        total_lines = len(text.splitlines())

        # ---- 3. 解析 + 校验 ----
        dist.stage = "validating"
        dist.progress = 20
        db.commit()
        warnings: list[str] = []
        strikes = lightning_statistics.parse_distribution_content(text, warnings=warnings)
        skipped_count = max(total_lines - len(strikes), 0)

        dist.total_lines = total_lines
        dist.valid_count = len(strikes)
        dist.skipped_count = skipped_count
        dist.warning_count = len(warnings)
        dist.warnings = warnings[:50]
        dist.stage = "statistics"
        dist.progress = 50
        db.commit()
        _append_log(log_parts, task_id, 
            f"[{task_id}] Parsed {len(strikes)} strikes, skipped={skipped_count}, "
            f"warnings={len(warnings)}"
        )

        # ---- 4. 统计 ----
        stats = lightning_statistics.compute_statistics(
            strikes,
            grid_size_km=float(dist.grid_size_km or 1.0),
            data_years=1.0,
        )
        dist.area_km2 = stats["area_km2"]
        dist.data_years = stats["data_years"]
        dist.overall_ng = stats["overall_ng"]
        dist.max_abs_current = stats["max_abs_current"]
        dist.avg_abs_current = stats["avg_abs_current"]
        dist.positive_count = stats["positive_count"]
        dist.negative_count = stats["negative_count"]
        dist.unknown_count = stats["unknown_count"]
        dist.stats_json = stats
        dist.progress = 75
        db.commit()
        _append_log(log_parts, task_id, 
            f"[{task_id}] Stats: area={stats['area_km2']:.3f}km², "
            f"Ng={stats['overall_ng']:.4f}"
        )

        # ---- 5. 出图（内部阶段） ----
        dist.stage = "rendering"
        db.commit()
        png = lightning_statistics.render_density_image(
            strikes,
            grid_size_km=float(dist.grid_size_km or 1.0),
            title=dist.source_file_name,
        )
        if png:
            image_key = minio_storage.build_image_key(dist.id)
            minio_storage.put_object(image_key, png, content_type="image/png")
            dist.image_object_key = image_key
            _append_log(log_parts, task_id, f"[{task_id}] Image uploaded to {image_key}")
        else:
            _append_log(log_parts, task_id, f"[{task_id}] matplotlib unavailable, skip image rendering")

        dist.status = "completed"
        dist.progress = 100
        db.commit()

        _upload_log(task_id, log_parts)
        return {
            "status": "completed",
            "distribution_id": dist.id,
            "valid_count": len(strikes),
            "skipped_count": skipped_count,
            "warning_count": len(warnings),
        }

    except Exception as exc:
        import traceback

        db.rollback()
        _append_log(log_parts, task_id, f"[{task_id}] FAILED: {exc}")
        _append_log(log_parts, task_id, traceback.format_exc())
        _upload_log(task_id, log_parts)
        try:
            dist = db.execute(
                select(LightningDistribution).where(LightningDistribution.id == distribution_id)
            ).scalar_one_or_none()
            if dist:
                dist.status = "failed"
                dist.error_message = str(exc)
                db.commit()
        except Exception:
            db.rollback()
        raise

    finally:
        db.close()


@celery_app.task(
    name="app.tasks.lightning_tasks.fill_line_lightning_density_job",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def fill_line_lightning_density_job(
    self,
    line_id: str,
    region_id: str | None = None,
    years: float | None = None,
    radius_km: float | None = None,
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    """
    线路地闪密度回填任务（原 compute_ground_flash_density_job 改造）。

    落雷数据来源（LightningDistributionPoint 已删除，禁止再读该表）：
      a. 优先：该线路关联的 LightningDistribution（status=completed）
      b. 从关联分布的 MinIO 原始文件（source_object_key）下载并重新解析
      c. 若线路未关联分布或 MinIO 无文件：回填中止并回报原因

    Steps:
      1) 查询线路 + 杆塔，确定分组参数
      2) 按 voltage_kv 分组（group_size 基一组）
      3) 读取落雷集合（MinIO 原始文件）
      4) 最近邻分配 + Ng 计算
      5) 回填 LineTower.lightning_density
    """
    task_id = self.request.id
    log_parts: list[str] = [
        f"[{task_id}] Starting line lightning density fill",
        f"  line_id={line_id}, region_id={region_id}, years={years}, radius_km={radius_km}",
    ]

    db: Session = SessionLocal()
    try:
        from ..services import minio_storage
        from ..services import lightning_statistics

        # ---- 步骤 1：获取线路和杆塔 ----
        line = db.execute(select(Line).where(Line.id == line_id)).scalar_one_or_none()
        if not line:
            _append_log(log_parts, task_id, f"[{task_id}] Line {line_id} not found, aborting")
            _upload_log(task_id, log_parts)
            return {"status": "failed", "error": "line not found"}

        group_size, radius_km_resolved, num4 = _resolve_params_for_voltage(line.voltage_kv)
        if radius_km is not None:
            radius_km_resolved = radius_km
        _append_log(log_parts, task_id, 
            f"[{task_id}] Line '{line.name}' voltage={line.voltage_kv}kV -> "
            f"group_size={group_size}, radius={radius_km_resolved}km, num4={num4}"
        )

        towers = db.execute(
            select(LineTower)
            .where(LineTower.line_id == line.id)
            .order_by(LineTower.seq_no.asc(), LineTower.id.asc())
        ).scalars().all()

        if not towers:
            _append_log(log_parts, task_id, f"[{task_id}] No towers found for line {line_id}, aborting")
            _upload_log(task_id, log_parts)
            return {"status": "failed", "error": "no towers"}

        # ---- 步骤 2：杆塔分组 ----
        geo_towers = [
            t for t in towers
            if t.longitude is not None and t.latitude is not None
        ]
        if not geo_towers:
            _append_log(log_parts, task_id, f"[{task_id}] No towers with geo coordinates, aborting")
            _upload_log(task_id, log_parts)
            return {"status": "failed", "error": "no geo towers"}

        _append_log(log_parts, task_id, f"[{task_id}] Total towers={len(towers)}, with_geo={len(geo_towers)}")

        groups: list[dict[str, Any]] = []
        for i in range(0, len(geo_towers), group_size):
            chunk = geo_towers[i : i + group_size]
            avg_lat = sum(float(t.latitude) for t in chunk) / len(chunk)
            avg_lon = sum(float(t.longitude) for t in chunk) / len(chunk)
            groups.append({
                "group_id": i // group_size,
                "tower_ids": [t.id for t in chunk],
                "center_lat": avg_lat,
                "center_lon": avg_lon,
            })

        _append_log(log_parts, task_id, f"[{task_id}] Created {len(groups)} groups")

        # ---- 步骤 3：读取落雷集合（仅来自 LightningDistribution + MinIO）----
        dist = db.execute(
            select(LightningDistribution)
            .where(
                LightningDistribution.line_id == line.id,
                LightningDistribution.status == "completed",
            )
            .order_by(LightningDistribution.create_date.desc())
        ).scalars().first()

        if not dist or not dist.source_object_key:
            _append_log(log_parts, task_id, 
                f"[{task_id}] No completed LightningDistribution for line {line_id}, "
                f"fill aborted (point table is no longer used)"
            )
            _upload_log(task_id, log_parts)
            return {"status": "failed", "error": "no distribution data for line"}

        try:
            content = minio_storage.get_object(dist.source_object_key)
        except Exception as exc:
            _append_log(log_parts, task_id, f"[{task_id}] Failed to read source file from MinIO: {exc}")
            _upload_log(task_id, log_parts)
            return {"status": "failed", "error": f"minio read failed: {exc}"}

        try:
            text = lightning_statistics.decode_text_bytes(content)
        except Exception as exc:
            _append_log(log_parts, task_id, f"[{task_id}] Failed to decode source file: {exc}")
            _upload_log(task_id, log_parts)
            return {"status": "failed", "error": f"decode failed: {exc}"}

        all_strikes = lightning_statistics.parse_distribution_content(text)
        if not all_strikes:
            _append_log(log_parts, task_id, f"[{task_id}] No strikes parsed from source file, aborting")
            _upload_log(task_id, log_parts)
            return {"status": "failed", "error": "no strikes in source file"}

        # 过滤：仅保留杆塔包围盒附近的落雷
        min_lat = min(g["center_lat"] for g in groups) - (radius_km_resolved / _DEGREE_TO_KM)
        max_lat = max(g["center_lat"] for g in groups) + (radius_km_resolved / _DEGREE_TO_KM)
        min_lon = min(g["center_lon"] for g in groups) - (
            radius_km_resolved / _safe_km_per_lon(groups[0]["center_lat"])
        )
        max_lon = max(g["center_lon"] for g in groups) + (
            radius_km_resolved / _safe_km_per_lon(groups[0]["center_lat"])
        )

        lightning_strikes = [
            {
                "lat": float(s["lat"]),
                "lon": float(s["lon"]),
            }
            for s in all_strikes
            if (
                s["lat"] is not None
                and s["lon"] is not None
                and min_lat <= float(s["lat"]) <= max_lat
                and min_lon <= float(s["lon"]) <= max_lon
            )
        ]

        if not lightning_strikes:
            _append_log(log_parts, task_id, f"[{task_id}] No lightning data in bounding box, returning empty")
            _upload_log(task_id, log_parts)
            return {"status": "done", "updated_tower_count": 0, "note": "no lightning data"}

        # 数据年数
        if years is not None and years > 0:
            data_years = float(years)
        else:
            data_years = max(float(dist.data_years or 1.0), 1e-6)

        _append_log(log_parts, task_id, 
            f"[{task_id}] Found {len(lightning_strikes)} strikes, data_years={data_years:.2f}"
        )

        # ---- 步骤 4：Ng 计算 ----
        ng_per_group = _compute_ng_per_group(
            groups, lightning_strikes, data_years, radius_km_resolved
        )

        # ---- 步骤 5：回填杆塔 ----
        updated_count = 0
        now = datetime.utcnow()
        for group in groups:
            gid = group["group_id"]
            ng_value = ng_per_group.get(gid, 0.0)
            tower_ids = group["tower_ids"]
            for tid in tower_ids:
                tower = next((t for t in towers if t.id == tid), None)
                if not tower:
                    continue
                tower.lightning_density = ng_value
                extra = dict(tower.raw_extra_json or {})
                extra["lightning_density"] = {
                    "value": ng_value,
                    "group_id": gid,
                    "radius_km": radius_km_resolved,
                    "data_years": data_years,
                    "computed_at": now.isoformat(),
                    "source_distribution_id": dist.id,
                }
                tower.raw_extra_json = extra
                tower.update_user = actor_user_id
                updated_count += 1

        db.commit()
        _append_log(log_parts, task_id, f"[{task_id}] Updated {updated_count} towers with Ng values")

        _upload_log(task_id, log_parts)
        return {
            "status": "done",
            "updated_tower_count": updated_count,
            "groups": len(groups),
            "strikes_found": len(lightning_strikes),
        }

    except Exception as exc:
        db.rollback()
        import traceback

        _append_log(log_parts, task_id, f"[{task_id}] FAILED: {exc}")
        _append_log(log_parts, task_id, traceback.format_exc())
        _upload_log(task_id, log_parts)
        raise

    finally:
        db.close()


# ---------------------------------------------------------------------------
# 异步雷电流幅值导入任务（对标 import_lightning_distribution_job）
# ---------------------------------------------------------------------------
@celery_app.task(
    name="app.tasks.lightning_tasks.import_lightning_amplitude_job",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    acks_late=True,
)
def import_lightning_amplitude_job(
    self,
    amplitude_id: str,
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    """
    雷电流幅值导入一条龙任务。

    Steps:
      1) 按 id 取 LightningAmplitude，status=processing / progress=10
      2) 从 MinIO 下载 source_object_key → 字节流
      3) 解码（utf-8-sig → utf-8 → gbk → latin-1）→ _parse_current_series 解析电流/时间序列
      4) 校验：采样点 < 2 → 失败；> MAX_SAMPLES → 失败
      5) _build_time_axis 构建时间轴（推断采样间隔/频率）
      6) _extract_wave_features 提取 8 类特征（峰值/极性/T1/T2/陡度/动作积分/波形分类/多重回击）
         —— 解析逻辑全部复用现有纯函数，只是不写 Sample 表
      7) 统计回写新表：sample_count / sample_interval_us / sampling_frequency_hz + 全部特征字段
      8) event_id 为空则任务内自动生成
      9) status=completed / progress=100，发布 lightning.created 通知

    失败路径：异常 → status=failed + error_message + progress 保留 → 前端展示失败原因，可点「重试」。
    """
    task_id = self.request.id
    log_parts: list[str] = [f"[{task_id}] Starting amplitude import: {amplitude_id}"]

    db: Session = SessionLocal()
    try:
        from ..services import minio_storage
        from ..services.lightning_service import (
            MAX_SAMPLES,
            _build_time_axis,
            _decode_text_bytes,
            _extract_wave_features,
            _generate_event_id,
            _normalize_str,
            _parse_current_series,
        )

        amp = db.execute(
            select(LightningAmplitude).where(LightningAmplitude.id == amplitude_id)
        ).scalar_one_or_none()
        if not amp:
            _append_log(log_parts, task_id, f"[{task_id}] Amplitude {amplitude_id} not found, aborting")
            _upload_log(task_id, log_parts)
            return {"status": "failed", "error": "amplitude not found"}

        amp.status = "processing"
        amp.progress = 10
        amp.task_id = task_id
        db.commit()
        _append_log(log_parts, task_id, f"[{task_id}] source_object_key={amp.source_object_key}")

        # ---- 2. 从 MinIO 下载原始文件 ----
        content = minio_storage.get_object(amp.source_object_key)
        text = _decode_text_bytes(content)

        # ---- 3. 解析 + 校验 ----
        parsed = _parse_current_series(text)
        if len(parsed.currents_ka) < 2:
            raise ValueError("有效采样点数量不足（至少需要 2 个点）")
        if len(parsed.currents_ka) > MAX_SAMPLES:
            raise ValueError(f"采样点过多（>{MAX_SAMPLES}），请拆分后再导入")

        amp.progress = 30
        db.commit()
        _append_log(log_parts, task_id,
            f"[{task_id}] Parsed {len(parsed.currents_ka)} samples, "
            f"warnings={len(parsed.warnings)}"
        )

        # ---- 4. 时间轴 ----
        time_axis_us, inferred_interval_us, inferred_fs_hz, time_warnings = _build_time_axis(
            parsed.time_us,
            sample_interval_us=amp.sample_interval_us,
            sample_count=len(parsed.currents_ka),
        )
        warnings = [*parsed.warnings, *time_warnings]

        # ---- 5. 特征提取（复用现有纯函数，不写 Sample 表）----
        features = _extract_wave_features(parsed.currents_ka, time_axis_us, inferred_interval_us)
        amp.progress = 70
        db.commit()

        # ---- 6. 统计回写 ----
        if not amp.event_id:
            amp.event_id = _generate_event_id()
        amp.sample_count = len(parsed.currents_ka)
        amp.sample_interval_us = inferred_interval_us
        amp.sampling_frequency_hz = inferred_fs_hz
        amp.peak_current_ka = features.peak_current_ka
        amp.peak_abs_current_ka = features.peak_abs_current_ka
        amp.wavefront_time_t1_us = features.wavefront_time_t1_us
        amp.half_value_time_t2_us = features.half_value_time_t2_us
        amp.steepness_ka_per_us = features.steepness_ka_per_us
        amp.action_integral_j_ohm = features.action_integral_j_ohm
        amp.wave_shape = features.wave_shape
        amp.polarity = features.polarity
        amp.stroke_count = features.stroke_count
        amp.stroke_peaks_json = features.stroke_peaks_json
        amp.feature_json = {
            "source": "import-file",
            "has_explicit_time_axis": parsed.time_us is not None,
        }
        amp.update_user = actor_user_id

        amp.status = "completed"
        amp.progress = 100
        db.commit()
        _append_log(log_parts, task_id,
            f"[{task_id}] Completed: peak={amp.peak_abs_current_ka}kA, "
            f"samples={amp.sample_count}, shape={amp.wave_shape}"
        )
        _upload_log(task_id, log_parts)

        # ---- 7. 发布通知 ----
        try:
            from ..services.lightning_service import _publish_lightning_change
            _publish_lightning_change(
                "lightning.created",
                {"event_id": amp.id, "message": f"雷电流幅值导入完成：{amp.source_file_name}"},
            )
        except Exception:
            pass

        return {
            "status": "completed",
            "amplitude_id": amp.id,
            "sample_count": amp.sample_count,
            "peak_abs_current_ka": amp.peak_abs_current_ka,
            "warnings": warnings[:50],
        }

    except Exception as exc:
        import traceback

        db.rollback()
        _append_log(log_parts, task_id, f"[{task_id}] FAILED: {exc}")
        _append_log(log_parts, task_id, traceback.format_exc())
        _upload_log(task_id, log_parts)
        try:
            amp = db.execute(
                select(LightningAmplitude).where(LightningAmplitude.id == amplitude_id)
            ).scalar_one_or_none()
            if amp:
                amp.status = "failed"
                amp.error_message = str(exc)
                amp.update_user = actor_user_id
                db.commit()
        except Exception:
            db.rollback()
        raise

    finally:
        db.close()
