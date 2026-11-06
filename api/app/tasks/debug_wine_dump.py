"""临时诊断任务：定位 wine 下 ATP `fmt: read unexpected character` 的真凶。

在 wine worker 现场对最近一次防雷任务的运行目录做变量实验，并把关键文件
上传到存储 debug-dumps/ 前缀，供本地复现对比。诊断完成后整个模块应删除。
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

from app.core.celery_app import celery_app

_ATP_ROOT = Path("/app/data/wine/ATP")
_WORKDIR_ROOT = Path("/app/data/wine/atp-models/runs/fl-analysis")


def _md5(p: Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _manifest(d: Path, limit: int = 400) -> list[dict]:
    out = []
    for p in sorted(d.rglob("*")):
        if not p.is_file() or len(out) >= limit:
            continue
        try:
            b = p.read_bytes()
        except Exception as exc:  # noqa: BLE001
            out.append({"f": str(p.relative_to(d)), "err": str(exc)})
            continue
        out.append({
            "f": str(p.relative_to(d)),
            "size": len(b),
            "md5": hashlib.md5(b).hexdigest(),
            "has_cr": b"\r" in b,
            "head": repr(b[:60]) if len(b) < 200000 else "",
        })
    return out


def _param_lines_without_eq(text: str) -> str:
    """$PARAMETER 段内：10 列参数名后直接跟数值（去掉 '='），其余行不动。"""
    lines = text.split("\n")
    in_param = False
    for i, ln in enumerate(lines):
        if ln.strip().upper().startswith("$PARAMETER"):
            in_param = True
            continue
        if in_param and ln.strip().upper().startswith("BLANK"):
            in_param = False
            continue
        if in_param and "=" in ln:
            name, _, val = ln.partition("=")
            lines[i] = f"{name:<10}{val}"
    return "\n".join(lines)


def _run_variant(tag: str, work_atp: str, workdir: Path) -> dict:
    vdir = Path(f"/tmp/dbg_{tag}")
    shutil.rmtree(vdir, ignore_errors=True)
    vdir.mkdir(parents=True)
    (vdir / "work.atp").write_bytes(work_atp.encode("utf-8", errors="surrogateescape"))
    try:
        proc = subprocess.run(
            ["wine", str(_ATP_ROOT / "mytpbig.exe"), "both", "work.atp", "s", "-r"],
            cwd=vdir, capture_output=True, text=True, timeout=600,
        )
        rc, err = proc.returncode, (proc.stderr or "")[-500:]
    except Exception as exc:  # noqa: BLE001
        return {"v": tag, "error": str(exc)}
    lis = vdir / "work.lis"
    closes = 0
    if lis.exists():
        closes = lis.read_text(errors="ignore").count("Close switch")
    shutil.rmtree(vdir, ignore_errors=True)
    return {"v": tag, "rc": rc, "stderr_tail": err, "close_switch": closes}


@celery_app.task(name="app.tasks.debug_wine_dump.debug_wine_probe")
def debug_wine_probe() -> dict:
    # 1. 找最近一次任务的 workdir（含 work.atp）
    candidates = sorted(
        _WORKDIR_ROOT.glob("*/*/work.atp"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not candidates:
        return {"error": "no work.atp found under fl-analysis"}
    work_atp_path = candidates[0]
    workdir = work_atp_path.parent

    # 2. 从 $INSERT 解析私有引擎目录
    text = work_atp_path.read_text(errors="ignore")
    m = re.search(r"\$INSERT,\s*(.+)", text)
    engine_dir = None
    if m:
        ins = m.group(1).strip().rstrip(", ")
        # wine D:\... → /app/data/wine/ATP/...
        mm = re.search(r"ATP[\\/](\.runs[\\/][^\\/]+)", ins, re.I)
        if mm:
            engine_dir = _ATP_ROOT / mm.group(1).replace("\\", "/")

    result: dict = {
        "workdir": str(workdir),
        "work_atp_size": work_atp_path.stat().st_size,
        "work_atp_has_cr": b"\r" in work_atp_path.read_bytes(),
        "engine_dir": str(engine_dir) if engine_dir else None,
        "engine_md5": _md5(_ATP_ROOT / "mytpbig.exe") if (_ATP_ROOT / "mytpbig.exe").exists() else None,
    }

    # 3. 引擎目录文件清单（含 \r 标记）
    if engine_dir and engine_dir.exists():
        result["engine_manifest"] = _manifest(engine_dir, limit=60)

    # 4. 变量实验（只改 workdir 副本里的 work.atp，不动引擎目录）
    raw = work_atp_path.read_bytes().decode("utf-8", errors="surrogateescape")
    result["v_asis"] = _run_variant("asis", raw, workdir)
    result["v_no_eq"] = _run_variant("noeq", _param_lines_without_eq(raw), workdir)
    result["v_no_cr"] = _run_variant("nocr", raw.replace("\r", ""), workdir)

    # 5. 关键文件上传存储（本地复现用）
    try:
        from app.core.database import SessionLocal
        from app.services.atp_asset_service import _resolve_mount, _build_driver_or_400

        db = SessionLocal()
        driver = _build_driver_or_400(_resolve_mount(db, "main"))
        tag = workdir.name[:8]
        uploads = [work_atp_path]
        if engine_dir and engine_dir.exists():
            uploads += [p for p in engine_dir.glob("*.lib")][:4]
            uploads += [p for p in engine_dir.glob("*.pch")][:2]
        for p in uploads:
            if p.is_file() and p.stat().st_size < 8_000_000:
                driver.write_file(
                    f"/debug-dumps/{tag}/{p.name}", content=p.read_bytes()
                )
        result["uploaded"] = [p.name for p in uploads if p.is_file()]
    except Exception as exc:  # noqa: BLE001
        result["upload_error"] = str(exc)

    return result
