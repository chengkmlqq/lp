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
from ..models.lightning_distribution import LightningDistributionPoint


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


def _compute_ng_with_shapely(
    groups: list[dict[str, Any]],
    lightning_strikes: list[dict[str, Any]],
    data_years: float,
    radius_km: float,
) -> dict[int, float]:
    """
    Shapely 实现（备用）：用缓冲区 + 最近邻分配。
    如果 shapely 可用则用精确区域，否则回退到普通缓冲区面积。
    """
    try:
        from shapely.geometry import Point
    except ImportError:
        # shapely 不可用，回退到简化版
        return _compute_ng_per_group(groups, lightning_strikes, data_years, radius_km)

    if not groups or not lightning_strikes or data_years <= 0:
        return {}

    group_centers: dict[int, tuple[float, float]] = {}
    group_buffers: dict[int, Any] = {}
    for g in groups:
        gid = g["group_id"]
        lat, lon = g["center_lat"], g["center_lon"]
        group_centers[gid] = (lat, lon)
        # 粗略地将 km 转为度（在中纬度地区近似）
        radius_deg = radius_km / _DEGREE_TO_KM
        group_buffers[gid] = Point(lon, lat).buffer(radius_deg)

    count_per_group: dict[int, int] = defaultdict(int)
    for strike in lightning_strikes:
        slat = strike["lat"]
        slon = strike["lon"]
        if slat is None or slon is None:
            continue
        strike_point = Point(slon, slat)
        best_id = min(
            group_centers,
            key=lambda gid: _haversine_km(
                slat, slon, group_centers[gid][0], group_centers[gid][1]
            ),
        )
        # 检查落在缓冲区内
        if strike_point.within(group_buffers[best_id]):
            count_per_group[best_id] += 1

    return {
        gid: count / (math.pi * radius_km ** 2 * data_years)
        for gid, count in count_per_group.items()
    }


# ---------------------------------------------------------------------------
# Celery 任务
# ---------------------------------------------------------------------------
@celery_app.task(
    name="app.tasks.lightning_tasks.compute_ground_flash_density_job",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def compute_ground_flash_density_job(
    self,
    line_id: str,
    region_id: str | None = None,
    is_synthetic: bool | None = None,
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    """
    地闪密度批量计算任务（对应桌面版 banjin 流程的 Web 化实现）。

    Steps:
      1) 查询线路 + 杆塔，确定分组参数
      2) 按 voltage_kv 分组（group_size 基一组）
      3) 查询雷电数据（已导入的 LightningCurrentEvent）
      4) 最近邻分配 + Ng 计算
      5) 回填 LineTower.lightning_density
    """
    task_id = self.request.id
    log_parts: list[str] = [
        f"[{task_id}] Starting ground flash density computation",
        f"  line_id={line_id}, region_id={region_id}, is_synthetic={is_synthetic}",
    ]

    db: Session = SessionLocal()
    try:
        # ---- 步骤 1：获取线路和杆塔 ----
        line = db.execute(select(Line).where(Line.id == line_id)).scalar_one_or_none()
        if not line:
            log_parts.append(f"[{task_id}] Line {line_id} not found, aborting")
            _upload_log(task_id, log_parts)
            return {"status": "failed", "error": "line not found"}

        group_size, radius_km, num4 = _resolve_params_for_voltage(line.voltage_kv)
        log_parts.append(
            f"[{task_id}] Line '{line.name}' voltage={line.voltage_kv}kV -> "
            f"group_size={group_size}, radius={radius_km}km, num4={num4}"
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

        # ---- 步骤 3：查询雷电数据 ----
        min_lat = min(g["center_lat"] for g in groups) - (radius_km / _DEGREE_TO_KM)
        max_lat = max(g["center_lat"] for g in groups) + (radius_km / _DEGREE_TO_KM)
        min_lon = min(g["center_lon"] for g in groups) - (
            radius_km / _safe_km_per_lon(groups[0]["center_lat"])
        )
        max_lon = max(g["center_lon"] for g in groups) + (
            radius_km / _safe_km_per_lon(groups[0]["center_lat"])
        )

        filters = [
            LightningDistributionPoint.longitude >= min_lon,
            LightningDistributionPoint.longitude <= max_lon,
            LightningDistributionPoint.latitude >= min_lat,
            LightningDistributionPoint.latitude <= max_lat,
        ]
        if region_id:
            filters.append(LightningDistributionPoint.region_id == region_id)
        if is_synthetic is not None:
            filters.append(LightningDistributionPoint.is_synthetic == is_synthetic)

        storm_rows = db.execute(
            select(
                LightningDistributionPoint.longitude,
                LightningDistributionPoint.latitude,
                LightningDistributionPoint.event_time,
            ).where(*filters)
        ).all()

        if not storm_rows:
            log_parts.append(f"[{task_id}] No lightning data found in bounding box, returning empty")
            _upload_log(task_id, log_parts)
            return {"status": "done", "updated_tower_count": 0, "note": "no lightning data"}

        lightning_strikes = [
            {"lat": float(r.latitude), "lon": float(r.longitude), "time": r.event_time}
            for r in storm_rows
            if r.latitude is not None and r.longitude is not None
        ]

        # 确定数据年数
        all_times = [r.event_time for r in storm_rows if r.event_time is not None]
        if all_times:
            min_time = min(all_times)
            max_time = max(all_times)
            data_years = max((max_time - min_time).days / 365.25, 0.5)
        else:
            data_years = 1.0

        log_parts.append(
            f"[{task_id}] Found {len(lightning_strikes)} strikes, data_years={data_years:.2f}"
        )

        # ---- 步骤 4：Ng 计算 ----
        ng_per_group = _compute_ng_per_group(
            groups, lightning_strikes, data_years, radius_km
        )

        # ---- 步骤 5：回填杆塔 ----
        updated_count = 0
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
                    "radius_km": radius_km,
                    "computed_at": datetime.utcnow().isoformat(),
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


def _upload_log(task_id: str, log_parts: list[str]) -> None:
    """上传任务日志（非致命错误）"""
    try:
        from ..services.task_log_service import upload_task_log

        upload_task_log(task_id, "\n".join(log_parts))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 异步雷电分布数据导入任务
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
        raise


@celery_app.task(
    name="app.tasks.lightning_tasks.import_lightning_distribution_job",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    acks_late=True,
)
def import_lightning_distribution_job(
    self,
    batch_id: str,
    file_path: str,
    source_file_name: str | None = None,
    actor_user_id: str | None = None,
    event_year: int | None = None,
    region_id: str | None = None,
    location_tag: str | None = None,
    city: str | None = None,
    notes: str | None = None,
    is_synthetic: bool = False,
    line_id: str | None = None,
) -> dict[str, Any]:
    """
    在 Celery Worker 后台执行雷电分布数据导入。
    从共享卷读取临时文件 → 解析 → batch insert → 清理临时文件。
    """
    task_id = self.request.id
    log_parts: list[str] = [f"[{task_id}] Starting distribution import: {source_file_name}"]

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
        from ..services.lightning_service import execute_distribution_import_from_path

        result = execute_distribution_import_from_path(
            file_path=file_path,
            source_file_name=source_file_name,
            actor_user_id=actor_user_id or "system",
            event_year=event_year,
            region_id=region_id,
            location_tag=location_tag,
            city=city,
            notes=notes,
            is_synthetic=is_synthetic,
            line_id=line_id,
        )

        log_parts.append(
            f"[{task_id}] Done: imported={result.get('imported_count')}, "
            f"skipped={result.get('skipped_count')}, "
            f"warnings={len(result.get('warnings', []))}"
        )
        _upload_log(task_id, log_parts)

        # Update batch status to completed
        _session2 = SessionLocal()
        try:
            _batch2 = _session2.query(LightningImportBatch).filter(LightningImportBatch.id == batch_id).first()
            if _batch2:
                _batch2.status = "completed"
                _batch2.event_count = result.get("imported_count", 0)
                _batch2.skipped_count = result.get("skipped_count", 0)
                _batch2.warning_count = result.get("warning_count", 0)
                _session2.commit()
        except Exception:
            _session2.rollback()
        finally:
            _session2.close()

        return result

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
