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
from ..models.lightning_distribution import LightningDistribution
from ..models.lightning_event import LightningCurrentEvent


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
def _upload_log(task_id: str, log_parts: list[str]) -> None:
    """上传任务日志（非致命错误）"""
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
            log_parts.append(f"[{task_id}] Distribution {distribution_id} not found, aborting")
            _upload_log(task_id, log_parts)
            return {"status": "failed", "error": "distribution not found"}

        dist.status = "processing"
        dist.stage = "parsing"
        dist.progress = 5
        dist.task_id = task_id
        db.commit()
        log_parts.append(f"[{task_id}] source_object_key={dist.source_object_key}")

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
        log_parts.append(
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
        log_parts.append(
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
            log_parts.append(f"[{task_id}] Image uploaded to {image_key}")
        else:
            log_parts.append(f"[{task_id}] matplotlib unavailable, skip image rendering")

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
        log_parts.append(f"[{task_id}] FAILED: {exc}")
        log_parts.append(traceback.format_exc())
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
            log_parts.append(f"[{task_id}] Line {line_id} not found, aborting")
            _upload_log(task_id, log_parts)
            return {"status": "failed", "error": "line not found"}

        group_size, radius_km_resolved, num4 = _resolve_params_for_voltage(line.voltage_kv)
        if radius_km is not None:
            radius_km_resolved = radius_km
        log_parts.append(
            f"[{task_id}] Line '{line.name}' voltage={line.voltage_kv}kV -> "
            f"group_size={group_size}, radius={radius_km_resolved}km, num4={num4}"
        )

        towers = db.execute(
            select(LineTower)
            .where(LineTower.line_id == line.id)
            .order_by(LineTower.seq_no.asc(), LineTower.id.asc())
        ).scalars().all()

        if not towers:
            log_parts.append(f"[{task_id}] No towers found for line {line_id}, aborting")
            _upload_log(task_id, log_parts)
            return {"status": "failed", "error": "no towers"}

        # ---- 步骤 2：杆塔分组 ----
        geo_towers = [
            t for t in towers
            if t.longitude is not None and t.latitude is not None
        ]
        if not geo_towers:
            log_parts.append(f"[{task_id}] No towers with geo coordinates, aborting")
            _upload_log(task_id, log_parts)
            return {"status": "failed", "error": "no geo towers"}

        log_parts.append(f"[{task_id}] Total towers={len(towers)}, with_geo={len(geo_towers)}")

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

        log_parts.append(f"[{task_id}] Created {len(groups)} groups")

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
            log_parts.append(
                f"[{task_id}] No completed LightningDistribution for line {line_id}, "
                f"fill aborted (point table is no longer used)"
            )
            _upload_log(task_id, log_parts)
            return {"status": "failed", "error": "no distribution data for line"}

        try:
            content = minio_storage.get_object(dist.source_object_key)
        except Exception as exc:
            log_parts.append(f"[{task_id}] Failed to read source file from MinIO: {exc}")
            _upload_log(task_id, log_parts)
            return {"status": "failed", "error": f"minio read failed: {exc}"}

        try:
            text = lightning_statistics.decode_text_bytes(content)
        except Exception as exc:
            log_parts.append(f"[{task_id}] Failed to decode source file: {exc}")
            _upload_log(task_id, log_parts)
            return {"status": "failed", "error": f"decode failed: {exc}"}

        all_strikes = lightning_statistics.parse_distribution_content(text)
        if not all_strikes:
            log_parts.append(f"[{task_id}] No strikes parsed from source file, aborting")
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
            log_parts.append(f"[{task_id}] No lightning data in bounding box, returning empty")
            _upload_log(task_id, log_parts)
            return {"status": "done", "updated_tower_count": 0, "note": "no lightning data"}

        # 数据年数
        if years is not None and years > 0:
            data_years = float(years)
        else:
            data_years = max(float(dist.data_years or 1.0), 1e-6)

        log_parts.append(
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
        log_parts.append(f"[{task_id}] Updated {updated_count} towers with Ng values")

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

        log_parts.append(f"[{task_id}] FAILED: {exc}")
        log_parts.append(traceback.format_exc())
        _upload_log(task_id, log_parts)
        raise

    finally:
        db.close()


# ---------------------------------------------------------------------------
# 异步雷电流波形数据导入任务（保持现有实现，依赖 LightningImportBatch）
# ---------------------------------------------------------------------------
@celery_app.task(
    name="app.tasks.lightning_tasks.import_lightning_current_job",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    acks_late=True,
)
def import_lightning_current_job(
    self,
    batch_id: str,
    file_path: str,
    source_file_name: str | None = None,
    actor_user_id: str | None = None,
    event_id: str | None = None,
    event_time: str | None = None,
    sample_interval_us: float | None = None,
    region_id: str | None = None,
    location_tag: str | None = None,
    city: str | None = None,
    longitude: float | None = None,
    latitude: float | None = None,
    altitude_m: float | None = None,
    sensor_model: str | None = None,
    install_position: str | None = None,
    weather_level: str | None = None,
    pressure_hpa: float | None = None,
    humidity_percent: float | None = None,
    is_synthetic: bool = False,
    notes: str | None = None,
) -> dict[str, Any]:
    """
    在 Celery Worker 后台执行雷电流波形数据导入。
    从共享卷读取临时文件 → 解析 → batch insert → 清理临时文件。
    """
    task_id = self.request.id
    log_parts: list[str] = [f"[{task_id}] Starting current import: {source_file_name}"]

    # Update batch status to processing
    from ..core.database import SessionLocal
    from ..models.lightning_import_batch import LightningImportBatch
    _session = SessionLocal()
    try:
        _batch = _session.query(LightningImportBatch).filter(LightningImportBatch.id == batch_id).first()
        if _batch:
            _batch.status = "processing"
            _session.commit()
    except Exception:
        _session.rollback()
    finally:
        _session.close()

    try:
        from ..services.lightning_service import execute_current_import_from_path

        result = execute_current_import_from_path(
            file_path=file_path,
            source_file_name=source_file_name,
            actor_user_id=actor_user_id or "system",
            event_id=event_id,
            event_time_str=event_time,
            sample_interval_us=sample_interval_us,
            region_id=region_id,
            location_tag=location_tag,
            city=city,
            longitude=longitude,
            latitude=latitude,
            altitude_m=altitude_m,
            sensor_model=sensor_model,
            install_position=install_position,
            weather_level=weather_level,
            pressure_hpa=pressure_hpa,
            humidity_percent=humidity_percent,
            is_synthetic=is_synthetic,
            notes=notes,
        )

        log_parts.append(
            f"[{task_id}] Done: imported={result.imported_count}, "
            f"skipped={result.skipped_count}, "
            f"warnings={result.warning_count}"
        )
        _upload_log(task_id, log_parts)

        # Update batch status to completed
        _session2 = SessionLocal()
        try:
            _batch2 = _session2.query(LightningImportBatch).filter(LightningImportBatch.id == batch_id).first()
            if _batch2:
                _batch2.status = "completed"
                _batch2.event_count = result.imported_count
                _batch2.skipped_count = result.skipped_count
                _batch2.warning_count = result.warning_count
                _session2.commit()
        except Exception:
            _session2.rollback()
        finally:
            _session2.close()

        return {
            "imported_count": result.imported_count,
            "skipped_count": result.skipped_count,
            "warning_count": result.warning_count,
            "warnings": result.warnings,
        }

    except Exception as exc:
        import traceback

        log_parts.append(f"[{task_id}] FAILED: {exc}")
        log_parts.append(traceback.format_exc())
        _upload_log(task_id, log_parts)

        # Update batch status to failed
        _session3 = SessionLocal()
        try:
            _batch3 = _session3.query(LightningImportBatch).filter(LightningImportBatch.id == batch_id).first()
            if _batch3:
                _batch3.status = "failed"
                _batch3.error_message = str(exc)
                _session3.commit()
        except Exception:
            _session3.rollback()
        finally:
            _session3.close()

        raise
