from __future__ import annotations

from typing import Any

from sqlalchemy import select, func as sa_func
from sqlalchemy.orm import Session

from ..core.celery_app import celery_app
from ..core.config import get_settings
from ..core.database import SessionLocal
from ..models.line import Line
from ..models.line_tower import LineTower
from ..models.lightning_amplitude import LightningAmplitude
from ..models.lightning_current_backfill import LightningCurrentBackfillTask
from ..models.lightning_density_backfill import LightningDensityBackfillTask
from ..models.lightning_distribution import LightningDistribution
from ..services.lightning_service import (
    LIGHTNING_AMPLITUDE_TOPIC,
    LIGHTNING_CURRENT_BACKFILL_TOPIC,
    LIGHTNING_DISTRIBUTION_TOPIC,
)


# ---------------------------------------------------------------------------
# WebSocket 事件推送辅助
#
# Celery worker 与 FastAPI(Web) 进程分离，WS 连接持有在 Web 进程内存的
# ws_connection_manager 中；worker 直接调用 publish_topic() 会投递到 worker
# 自己进程内空的连接管理器，消息被静默丢弃。因此统一走 Redis Stream 事件桥
# （ws_event_bridge），由 Web 进程转发给对应 topic 的订阅者。
# ---------------------------------------------------------------------------
def _publish_distribution_event(event_name: str, payload: dict[str, Any]) -> None:
    """向 admin.lightning-distribution 主题推送地闪密度导入事件（经 Redis 桥）。"""
    try:
        from ..services.ws_event_bridge import publish_ws_event_from_worker

        publish_ws_event_from_worker(
            LIGHTNING_DISTRIBUTION_TOPIC,
            name=event_name,
            payload=payload,
            requires_refetch=["/api/v1/lightning-currents/distributions"],
            dedupe_key=f"{event_name}:{payload.get('distribution_id', 'unknown')}",
        )
    except Exception:
        pass


def _publish_amplitude_event(event_name: str, payload: dict[str, Any]) -> None:
    """向 admin.lightning-amplitude 主题推送雷电流幅值导入事件（经 Redis 桥）。"""
    try:
        from ..services.ws_event_bridge import publish_ws_event_from_worker

        publish_ws_event_from_worker(
            LIGHTNING_AMPLITUDE_TOPIC,
            name=event_name,
            payload=payload,
            requires_refetch=["/api/v1/lightning-currents/amplitudes"],
            dedupe_key=f"{event_name}:{payload.get('amplitude_id', 'unknown')}",
        )
    except Exception:
        pass


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
    # 该重任务处理 128.7 万条数据约耗时 106 分钟（约 6360s），
    # 设置软限制 2 小时（触发 SoftTimeLimitExceeded）、硬限制 3 小时，
    # 作为 visibility_timeout 之外的第二层兜底，避免超长任务失控。
    soft_time_limit=7200,
    time_limit=10800,
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
    log_parts: list[str] = [f"[{task_id}] 地闪分布导入任务启动（distribution_id={distribution_id}）"]

    db: Session = SessionLocal()
    try:
        from ..services import minio_storage
        from ..services import lightning_statistics

        dist = db.execute(
            select(LightningDistribution).where(LightningDistribution.id == distribution_id)
        ).scalar_one_or_none()
        if not dist:
            _append_log(log_parts, task_id,
                f"[{task_id}] 未找到地闪分布记录（id={distribution_id}），任务终止")
            _upload_log(task_id, log_parts)
            return {"status": "failed", "error": "distribution not found"}

        dist.status = "processing"
        dist.stage = "parsing"
        dist.progress = 5
        dist.task_id = task_id
        db.commit()
        _append_log(log_parts, task_id,
            f"[{task_id}] 开始导入地闪分布，文件：{dist.source_file_name}，"
            f"地点：{dist.region_id or '-'}（{dist.city or '-'}），年份：{dist.event_year}"
        )
        _publish_distribution_event("distribution.import_started", {
            "distribution_id": dist.id,
            "status": dist.status,
            "stage": dist.stage,
            "progress": dist.progress,
        })

        # ---- 2. 从 MinIO 下载原始文件 ----
        content = minio_storage.get_object(dist.source_object_key)
        text = lightning_statistics.decode_text_bytes(content)
        total_lines = len(text.splitlines())
        _append_log(log_parts, task_id,
            f"[{task_id}] 已下载源文件，共 {total_lines} 行原始数据，开始解析与校验"
        )

        # ---- 3. 解析 + 校验 ----
        dist.stage = "validating"
        dist.progress = 20
        db.commit()
        _publish_distribution_event("distribution.import_progress", {
            "distribution_id": dist.id,
            "stage": "validating",
            "progress": 20,
        })
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
        _publish_distribution_event("distribution.import_progress", {
            "distribution_id": dist.id,
            "stage": "statistics",
            "progress": 50,
        })
        _append_log(log_parts, task_id,
            f"[{task_id}] 解析完成：有效落雷 {len(strikes)} 条，跳过 {skipped_count} 条"
            f"（无法识别），预警 {len(warnings)} 条"
        )

        # ---- 4. 统计 ----
        # 观测年数解析优先级：导入时手动填写的 data_years > 从文件年份列自动推断 > 默认 1 年。
        # （GB/T 40621-2021：观测期不少于 10 个完整年；源数据如果不带时间无法自动判定。）
        resolved_years = dist.data_years
        if resolved_years is None or resolved_years <= 0:
            inferred = lightning_statistics.infer_observation_years(text)
            if inferred:
                resolved_years = inferred
                _append_log(log_parts, task_id,
                    f"[{task_id}] 未手动指定观测年数，已从文件年份自动推断为 {inferred:.0f} 年"
                )
        resolved_years = float(resolved_years or 1.0)

        stats = lightning_statistics.compute_statistics(
            strikes,
            grid_size_km=float(dist.grid_size_km or 1.0),
            data_years=resolved_years,
            # grid_cells 是纯内部计算的网格聚合明细（20 万格可占约 185MB），
            # 无 API/前端消费者，密度图由 render_density_image 从落点独立重聚合，
            # 故统计阶段不构建，避免巨大瞬时内存与序列化开销。
            include_grid_cells=False,
        )
        dist.area_km2 = stats["area_km2"]
        dist.data_years = stats["data_years"]
        dist.overall_ng = stats["overall_ng"]

        # 网格样本量校验（GB/T 40621-2021：单个网格 Ng × A_cell × T_obs >= 80）
        _cell_area = float(dist.grid_size_km or 1.0) ** 2
        if lightning_statistics.grid_sufficiency_ok(stats["overall_ng"], _cell_area, resolved_years):
            _append_log(log_parts, task_id,
                f"[{task_id}] 网格样本量校验通过（Ng×A×T >= 80）"
            )
        else:
            _append_log(log_parts, task_id,
                f"[{task_id}] 提示：单网格样本量 Ng×A×T={stats['overall_ng']:.3f}×{_cell_area:.2f}×{resolved_years:.1f} < 80，"
                f"网格偏小或观测期不足，建议核实数据观测期（国标≥10年）"
            )

        dist.max_abs_current = stats["max_abs_current"]
        dist.avg_abs_current = stats["avg_abs_current"]
        dist.positive_count = stats["positive_count"]
        dist.negative_count = stats["negative_count"]
        dist.unknown_count = stats["unknown_count"]
        dist.stats_json = {k: v for k, v in stats.items() if k != "grid_cells"}
        dist.progress = 75
        db.commit()
        _publish_distribution_event("distribution.import_progress", {
            "distribution_id": dist.id,
            "stage": "rendering",
            "progress": 75,
        })
        _max_cur = stats["max_abs_current"]
        _avg_cur = stats["avg_abs_current"]
        _max_text = f"{_max_cur:.2f}" if _max_cur is not None else "-"
        _avg_text = f"{_avg_cur:.2f}" if _avg_cur is not None else "-"
        _append_log(log_parts, task_id,
            f"[{task_id}] 统计完成：面积 {stats['area_km2']:.3f}km²，统计年限 {stats['data_years']}，"
            f"整体地闪密度 Ng={stats['overall_ng']:.4f}，"
            f"最大电流 {_max_text}kA，"
            f"平均电流 {_avg_text}kA，"
            f"正极性 {stats['positive_count']} 条 / "
            f"负极性 {stats['negative_count']} 条 / 未知 {stats['unknown_count']} 条"
        )

        # ---- 5. 出图（内部阶段） ----
        dist.stage = "rendering"
        db.commit()
        _append_log(log_parts, task_id, f"[{task_id}] 开始渲染地闪密度图（均匀网格）…")
        png = lightning_statistics.render_density_image(
            strikes,
            grid_size_km=float(dist.grid_size_km or 1.0),
            data_years=dist.data_years or 1.0,
            title=dist.source_file_name,
        )
        if png:
            image_key = minio_storage.build_image_key(dist.id)
            minio_storage.put_object(image_key, png, content_type="image/png")
            dist.image_object_key = image_key
            dist.lp_image_object_key = None  # 重新导入后旧 LP 分区图失效
            _append_log(log_parts, task_id,
                f"[{task_id}] 密度图渲染完成并已上传 ({image_key})"
            )
        else:
            _append_log(log_parts, task_id, f"[{task_id}] matplotlib 不可用，跳过密度图渲染")

        dist.status = "completed"
        dist.progress = 100
        db.commit()
        _publish_distribution_event("distribution.import_completed", {
            "distribution_id": dist.id,
            "status": "completed",
            "overall_ng": dist.overall_ng,
            "area_km2": dist.area_km2,
            "has_image": bool(dist.image_object_key),
            "valid_count": len(strikes),
            "skipped_count": skipped_count,
            "warning_count": len(warnings),
        })

        _upload_log(task_id, log_parts)
        _append_log(log_parts, task_id,
            f"[{task_id}] 地闪分布导入完成：有效 {len(strikes)} 条，跳过 {skipped_count} 条，"
            f"预警 {len(warnings)} 条，Ng={dist.overall_ng:.4f}"
        )
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
        _append_log(log_parts, task_id, f"[{task_id}] 任务执行失败：{exc}")
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
                _publish_distribution_event("distribution.import_failed", {
                    "distribution_id": dist.id,
                    "error": str(exc),
                })
        except Exception:
            db.rollback()
        raise

    finally:
        db.close()


# ---------------------------------------------------------------------------
# 临时文件清理（选择文件后未确认导入的孤儿文件）
# ---------------------------------------------------------------------------
@celery_app.task(
    name="app.tasks.lightning_tasks.cleanup_lightning_temp_files",
    ignore_result=True,
    track_started=False,
)
def cleanup_lightning_temp_files() -> dict[str, int]:
    """清理超过保留时长的 lightning/tmp/ 前缀临时文件，返回被删数量。"""
    settings = get_settings()
    from ..services import minio_storage

    deleted_count = minio_storage.cleanup_expired_temp_files(
        ttl_hours=settings.lightning_temp_file_ttl_hours,
    )
    return {
        "deleted_count": int(deleted_count),
    }


# ---------------------------------------------------------------------------
# LP 桌面端 Voronoi 分区密度图（异步重绘）
# ---------------------------------------------------------------------------
@celery_app.task(
    name="app.tasks.lightning_tasks.render_lp_density_job",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    acks_late=True,
    soft_time_limit=3600,
    time_limit=5400,
)
def render_lp_density_job(
    self,
    distribution_id: str,
    line_id: str,
    radius_km: float | None = None,
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    """按 LP 桌面端 Voronoi 分区算法，为指定线路关联的分布绘制分区密度图并传 MinIO。"""
    task_id = self.request.id
    log_parts: list[str] = [f"[{task_id}] LP 分区绘图任务启动（distribution={distribution_id}, line={line_id}）"]

    db: Session = SessionLocal()
    try:
        from ..services import minio_storage
        from ..services import lightning_statistics

        dist = db.execute(
            select(LightningDistribution).where(LightningDistribution.id == distribution_id)
        ).scalar_one_or_none()
        if not dist:
            _append_log(log_parts, task_id,
                f"[{task_id}] 未找到地闪分布记录（id={distribution_id}），任务终止")
            _upload_log(task_id, log_parts); return {"status": "failed", "error": "distribution not found"}
        if dist.status != "completed":
            _append_log(log_parts, task_id,
                f"[{task_id}] 地闪分布尚未完成导入（status={dist.status}），无法绘图")
            _upload_log(task_id, log_parts); return {"status": "failed", "error": "distribution not completed"}
        # 持久化绘图任务 task_id，供刷新页面后追溯绘图日志（LP-261）
        dist.lp_draw_task_id = task_id
        db.commit()
        _append_log(log_parts, task_id,
            f"[{task_id}] 地闪分布已完成导入，准备为线路绘制 LP 分区密度图"
        )

        line = db.execute(select(Line).where(Line.id == line_id)).scalar_one_or_none()
        if not line:
            _append_log(log_parts, task_id, f"[{task_id}] 未找到线路记录（line_id={line_id}）")
            _upload_log(task_id, log_parts); return {"status": "failed", "error": "line not found"}

        group_size, radius_km_resolved, _ = _resolve_params_for_voltage(line.voltage_kv)
        if radius_km is not None:
            radius_km_resolved = radius_km
        _append_log(log_parts, task_id,
            f"[{task_id}] 线路 {line.name}（{line.code}，{line.voltage_kv}kV），"
            f"分组大小={group_size}，缓冲半径={radius_km_resolved}km"
        )

        towers = db.execute(
            select(LineTower).where(LineTower.line_id == line.id)
            .order_by(LineTower.seq_no.asc(), LineTower.id.asc())
        ).scalars().all()
        geo = [t for t in towers if t.longitude is not None and t.latitude is not None]
        if not geo:
            _append_log(log_parts, task_id, f"[{task_id}] 线路 {line.name} 无带经纬度杆塔，无法绘图")
            _upload_log(task_id, log_parts); return {"status": "failed", "error": "no geo towers"}
        _append_log(log_parts, task_id,
            f"[{task_id}] 线路共 {len(towers)} 座杆塔，其中 {len(geo)} 座有经纬度，"
            f"将按每组 {group_size} 座生成 {((len(geo) + group_size - 1) // group_size)} 个 Voronoi 分区"
        )

        groups = []
        for i in range(0, len(geo), group_size):
            chunk = geo[i:i + group_size]
            groups.append({
                "group_id": i // group_size,
                "center_lat": sum(float(t.latitude) for t in chunk) / len(chunk),
                "center_lon": sum(float(t.longitude) for t in chunk) / len(chunk),
            })

        content = minio_storage.get_object(dist.source_object_key)
        text = lightning_statistics.decode_text_bytes(content)
        all_strikes = lightning_statistics.parse_distribution_content(text)
        if not all_strikes:
            _append_log(log_parts, task_id, f"[{task_id}] 源文件中未解析到有效落雷数据")
            _upload_log(task_id, log_parts); return {"status": "failed", "error": "no strikes"}
        _append_log(log_parts, task_id,
            f"[{task_id}] 源文件解析到 {len(all_strikes)} 条落雷数据，开始按线路包围盒裁剪"
        )

        # 裁剪到线路包围盒 + radius 缓冲
        DEG = 111.32
        import math as _m
        min_lat = min(g["center_lat"] for g in groups) - radius_km_resolved / DEG
        max_lat = max(g["center_lat"] for g in groups) + radius_km_resolved / DEG
        km_per_lon = DEG * _m.cos(_m.radians(groups[0]["center_lat"]))
        min_lon = min(g["center_lon"] for g in groups) - radius_km_resolved / max(km_per_lon, 1e-9)
        max_lon = max(g["center_lon"] for g in groups) + radius_km_resolved / max(km_per_lon, 1e-9)
        strikes = [s for s in all_strikes
                   if s["lat"] is not None and s["lon"] is not None
                   and min_lat <= float(s["lat"]) <= max_lat
                   and min_lon <= float(s["lon"]) <= max_lon]
        if not strikes:
            _append_log(log_parts, task_id,
                f"[{task_id}] 裁剪到线路包围盒后无落雷数据（源数据 {len(all_strikes)} 条，"
                f"包围盒：[{min_lat:.4f},{min_lon:.4f}] ~ [{max_lat:.4f},{max_lon:.4f}]）"
            )
            _upload_log(task_id, log_parts); return {"status": "failed", "error": "no strikes in bbox"}
        _append_log(log_parts, task_id,
            f"[{task_id}] 包围盒裁剪后剩余 {len(strikes)} 条落雷，开始计算 Voronoi 分区"
        )

        data_years = max(float(dist.data_years or 1.0), 1e-6)
        cells = lightning_statistics.compute_lp_voronoi_cells(groups, radius_km_resolved)
        if not cells:
            _append_log(log_parts, task_id, f"[{task_id}] Voronoi 分区计算失败")
            _upload_log(task_id, log_parts); return {"status": "failed", "error": "no voronoi cells"}
        _append_log(log_parts, task_id,
            f"[{task_id}] Voronoi 分区生成完成（{len(cells)} 个分区），开始渲染 LP 分区密度图"
        )

        png = lightning_statistics.render_lp_density_image(
            strikes, cells, data_years=data_years, radius_km=radius_km_resolved, title=line.name,
        )
        if not png:
            _append_log(log_parts, task_id, f"[{task_id}] matplotlib 不可用，无法渲染 LP 分区图")
            _upload_log(task_id, log_parts); return {"status": "failed", "error": "matplotlib unavailable"}
        _append_log(log_parts, task_id, f"[{task_id}] LP 分区密度图渲染完成，开始上传 MinIO…")

        build_key = f"lightning/dist/lp/{distribution_id}/{task_id}.png"
        minio_storage.put_object(build_key, png, content_type="image/png")
        dist.lp_image_object_key = build_key
        dist.update_user = actor_user_id
        db.commit()
        _append_log(log_parts, task_id, f"[{task_id}] LP 分区密度图已上传（{build_key}）")
        _publish_distribution_event("distribution.lp_draw_completed", {
            "distribution_id": dist.id, "status": "completed", "has_lp_image": True,
        })
        _upload_log(task_id, log_parts)
        _append_log(log_parts, task_id,
            f"[{task_id}] LP 分区密度图绘制完成（distribution={distribution_id}, line={line_id}）"
        )
        return {"status": "completed", "distribution_id": dist.id}

    except Exception as exc:
        db.rollback()
        import traceback
        _append_log(log_parts, task_id, f"[{task_id}] LP 绘图任务执行失败：{exc}")
        _append_log(log_parts, task_id, traceback.format_exc())
        _upload_log(task_id, log_parts)
        try:
            dist = db.execute(
                select(LightningDistribution).where(LightningDistribution.id == distribution_id)
            ).scalar_one_or_none()
            if dist:
                dist.error_message = str(exc)
                dist.lp_draw_task_id = task_id
                dist.update_user = actor_user_id
                db.commit()
                _publish_distribution_event("distribution.lp_draw_failed", {
                    "distribution_id": dist.id, "error": str(exc),
                })
        except Exception:
            db.rollback()
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
    log_parts: list[str] = [f"[{task_id}] 开始导入雷电流幅值：{amplitude_id}"]

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
            _append_log(log_parts, task_id, f"[{task_id}] 未找到幅值记录（{amplitude_id}），终止任务")
            _upload_log(task_id, log_parts)
            return {"status": "failed", "error": "amplitude not found"}

        _append_log(log_parts, task_id, f"[{task_id}] 源文件对象键：{amp.source_object_key}，文件名：{amp.source_file_name}")
        amp.status = "processing"
        amp.progress = 10
        amp.task_id = task_id
        db.commit()
        _publish_amplitude_event("amplitude.import_started", {
            "amplitude_id": amp.id,
            "status": amp.status,
            "progress": amp.progress,
        })

        # ---- 2. 从 MinIO 下载原始文件 ----
        log_parts.append(f"[{task_id}] 开始从 MinIO 下载源文件（{amp.source_object_key}）")
        content = minio_storage.get_object(amp.source_object_key)
        log_parts.append(f"[{task_id}] MinIO 下载完成，字节数：{len(content)}")
        text = _decode_text_bytes(content)
        log_parts.append(f"[{task_id}] 文件解码完成，文本行数：{len(text.splitlines())}")

        # ---- 3. 解析 + 校验 ----
        log_parts.append(f"[{task_id}] 开始解析电流序列...")
        parsed = _parse_current_series(text)
        log_parts.append(f"[{task_id}] 解析完成，采样点数量：{len(parsed.currents_ka)}，解析警告数：{len(parsed.warnings)}")
        if parsed.warnings:
            for warning in parsed.warnings[:5]:
                log_parts.append(f"[{task_id}] 解析警告：{warning}")
        if len(parsed.currents_ka) < 2:
            raise ValueError("有效采样点数量不足（至少需要 2 个点）")
        if len(parsed.currents_ka) > MAX_SAMPLES:
            raise ValueError(f"采样点过多（>{MAX_SAMPLES}），请拆分后再导入")

        amp.progress = 30
        db.commit()
        _publish_amplitude_event("amplitude.import_progress", {
            "amplitude_id": amp.id,
            "progress": 30,
        })
        _append_log(log_parts, task_id, f"[{task_id}] 解析校验通过，采样点数：{len(parsed.currents_ka)}")

        # ---- 4. 时间轴 ----
        log_parts.append(f"[{task_id}] 开始构建时间轴...")
        time_axis_us, inferred_interval_us, inferred_fs_hz, time_warnings = _build_time_axis(
            parsed.time_us,
            sample_interval_us=amp.sample_interval_us,
            sample_count=len(parsed.currents_ka),
        )
        log_parts.append(f"[{task_id}] 时间轴构建完成，采样间隔：{inferred_interval_us}us，采样频率：{inferred_fs_hz}Hz")
        if time_warnings:
            for warning in time_warnings[:5]:
                log_parts.append(f"[{task_id}] 时间轴警告：{warning}")
        warnings = [*parsed.warnings, *time_warnings]

        # ---- 5. 特征提取 ----
        log_parts.append(f"[{task_id}] 开始提取波形特征参数...")
        features = _extract_wave_features(parsed.currents_ka, time_axis_us, inferred_interval_us)
        log_parts.append(
            f"[{task_id}] 特征提取完成："
            f"峰值电流={features.peak_current_ka}kA，"
            f"绝对峰值={features.peak_abs_current_ka}kA，"
            f"波形分类={features.wave_shape}，"
            f"极性={features.polarity}，"
            f"波前时间T1={features.wavefront_time_t1_us}us，"
            f"半峰值时间T2={features.half_value_time_t2_us}us，"
            f"陡度={features.steepness_ka_per_us}kA/us，"
            f"I²t={features.action_integral_j_ohm}J/Ω，"
            f"多重回击数={features.stroke_count}"
        )
        amp.progress = 70
        db.commit()
        _publish_amplitude_event("amplitude.import_progress", {
            "amplitude_id": amp.id,
            "progress": 70,
        })

        # ---- 6. 统计回写 ----
        log_parts.append(f"[{task_id}] 开始回写特征数据到数据库...")
        if not amp.event_id:
            amp.event_id = _generate_event_id()
            log_parts.append(f"[{task_id}] 自动生成事件编号：{amp.event_id}")
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
            f"[{task_id}] 导入完成：绝对峰值={amp.peak_abs_current_ka}kA，"
            f"采样点数={amp.sample_count}，波形={amp.wave_shape}，"
            f"极性={amp.polarity}，多重回击={amp.stroke_count}次"
        )
        _upload_log(task_id, log_parts)

        # ---- 7. 发布通知 ----
        try:
            _publish_amplitude_event("amplitude.import_completed", {
                "amplitude_id": amp.id,
                "status": "completed",
                "sample_count": amp.sample_count,
                "peak_abs_current_ka": amp.peak_abs_current_ka,
                "wave_shape": amp.wave_shape,
                "source_file_name": amp.source_file_name,
            })
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
        _append_log(log_parts, task_id, f"[{task_id}] 导入失败：{exc}")
        _append_log(log_parts, task_id, f"[{task_id}] 异常堆栈：{traceback.format_exc()}")
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
                _publish_amplitude_event("amplitude.import_failed", {
                    "amplitude_id": amp.id,
                    "error": str(exc),
                })
        except Exception:
            db.rollback()
        raise

    finally:
        db.close()


def _publish_backfill_event(event_name: str, payload: dict[str, Any]) -> None:
    """向 admin.lightning-current-backfill 主题推送回填任务事件（经 Redis 桥）。"""
    try:
        from ..services.ws_event_bridge import publish_ws_event_from_worker

        publish_ws_event_from_worker(
            LIGHTNING_CURRENT_BACKFILL_TOPIC,
            name=event_name,
            payload=payload,
            requires_refetch=["/api/v1/lightning-currents/backfill-tasks"],
            dedupe_key=f"{event_name}:{payload.get('backfill_task_id', payload.get('line_id', 'unknown'))}",
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 异步线路雷电流幅值回填任务（LP-432：POST /prepare-current 异步化）
# ---------------------------------------------------------------------------
@celery_app.task(
    name="app.tasks.lightning_tasks.prepare_line_lightning_current_job",
    bind=True,
    queue="celery",
    max_retries=1,
    default_retry_delay=30,
    soft_time_limit=300,
    time_limit=600,
)
def prepare_line_lightning_current_job(
    self,
    line_id: str,
    region_id: str | None = None,
    is_synthetic: bool | None = None,
    backfill_task_id: str | None = None,
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    """
    异步执行线路雷电流幅值回填（API 已提前创建 pending 回填任务并派发本任务）。

    流程：标记 processing → 复用 LightningCurrentBackfillTask 记录执行计算 →
    推送 started / progress / completed / failed 事件。计算逻辑复用
    services.lightning_service._execute_line_lightning_current_backfill。
    """
    task_id = self.request.id
    log_parts: list[str] = [f"[{task_id}] 开始线路雷电流幅值回填：线路ID={line_id}"]

    db: Session = SessionLocal()
    try:
        from ..schemas.lightning import LightningCurrentPreparationRequest
        from ..services.lightning_service import _execute_line_lightning_current_backfill

        # 查询线路信息
        line = db.execute(select(Line).where(Line.id == line_id)).scalar_one_or_none()
        log_parts.append(
            f"[{task_id}] 线路信息：编号={line.code if line else 'N/A'}，名称={line.name if line else 'N/A'}"
            if line
            else f"[{task_id}] 线路未找到：{line_id}"
        )

        # 查询杆塔数量
        tower_count = db.execute(
            select(sa_func.count()).select_from(LineTower).where(LineTower.line_id == line_id)
        ).scalar() or 0
        log_parts.append(f"[{task_id}] 线路杆塔数：{tower_count}基")

        backfill_task = None
        if backfill_task_id:
            backfill_task = db.execute(
                select(LightningCurrentBackfillTask).where(LightningCurrentBackfillTask.id == backfill_task_id)
            ).scalar_one_or_none()
            if backfill_task:
                backfill_task.status = "processing"
                backfill_task.progress = 10
                backfill_task.task_id = task_id
                db.commit()
                log_parts.append(f"[{task_id}] 回填任务记录已更新为 processing（ID={backfill_task_id}）")

        _append_log(log_parts, task_id, f"[{task_id}] 回填参数：region_id={region_id}，is_synthetic={is_synthetic}")
        _publish_backfill_event("backfill.started", {
            "backfill_task_id": backfill_task_id or "",
            "line_id": line_id,
            "task_id": task_id,
            "status": "processing",
            "progress": 10,
        })

        payload = LightningCurrentPreparationRequest(
            line_id=line_id,
            region_id=region_id,
            is_synthetic=is_synthetic,
        )
        log_parts.append(f"[{task_id}] 开始执行回填计算（查询幅值记录→MinIO下载→解析→拟合→更新杆塔）...")
        result = _execute_line_lightning_current_backfill(
            db,
            payload,
            actor_user_id=actor_user_id or "system",
            backfill_task_id=backfill_task_id,
        )
        log_parts.append(
            f"[{task_id}] 回填计算完成："
            f"幅值a={result.current_a}kA，幅值b={result.current_b}kA，"
            f"峰值max={result.peak_max}kA，峰值min={result.peak_min}kA，"
            f"采样事件数={result.sampled_event_count}，"
            f"更新杆塔数={result.updated_tower_count}，"
            f"警告数={len(result.warnings)}"
        )
        if result.warnings:
            for warning in result.warnings[:10]:
                log_parts.append(f"[{task_id}] 回填警告：{warning}")
        _append_log(log_parts, task_id,
            f"[{task_id}] 回填完成：current_a={result.current_a}, current_b={result.current_b}, "
            f"towers={result.updated_tower_count}"
        )
        _upload_log(task_id, log_parts)
        _publish_backfill_event("backfill.completed", {
            "backfill_task_id": backfill_task_id or "",
            "line_id": line_id,
            "task_id": task_id,
            "status": "completed",
            "progress": 100,
            "current_a": result.current_a,
            "current_b": result.current_b,
            "updated_tower_count": result.updated_tower_count,
            "sampled_event_count": result.sampled_event_count,
            "warning_count": result.warning_count,
            "warnings": result.warnings[:50],
        })
        return {
            "status": "completed",
            "line_id": line_id,
            "backfill_task_id": backfill_task_id,
            "current_a": result.current_a,
            "current_b": result.current_b,
            "updated_tower_count": result.updated_tower_count,
        }

    except Exception as exc:
        import traceback

        db.rollback()
        _append_log(log_parts, task_id, f"[{task_id}] 回填失败：{exc}")
        _append_log(log_parts, task_id, f"[{task_id}] 异常堆栈：{traceback.format_exc()}")
        _upload_log(task_id, log_parts)
        try:
            if backfill_task_id:
                failed_task = db.execute(
                    select(LightningCurrentBackfillTask).where(LightningCurrentBackfillTask.id == backfill_task_id)
                ).scalar_one_or_none()
                if failed_task:
                    failed_task.status = "failed"
                    failed_task.error_message = str(exc)
                    db.commit()
            _publish_backfill_event("backfill.failed", {
                "backfill_task_id": backfill_task_id or "",
                "line_id": line_id,
                "task_id": task_id,
                "status": "failed",
                "error": str(exc),
            })
        except Exception:
            db.rollback()
        return {"status": "failed", "line_id": line_id, "backfill_task_id": backfill_task_id, "error": str(exc)}

    finally:
        db.close()


# ---------------------------------------------------------------------------
# 异步线路地闪密度回填任务（LP：POST /prepare-density 异步化）
# ---------------------------------------------------------------------------
def _publish_density_backfill_event(event_name: str, payload: dict[str, Any]) -> None:
    """向 admin.lightning-distribution 主题推送地闪密度回填任务事件（经 Redis 桥）。

    requires_refetch 覆盖分布列表接口；回填历史接口由页面订阅处理器
    refreshAll() 统一失效（前缀匹配 /api/v1/lightning-currents）。
    """
    try:
        from ..services.ws_event_bridge import publish_ws_event_from_worker

        publish_ws_event_from_worker(
            LIGHTNING_DISTRIBUTION_TOPIC,
            name=event_name,
            payload=payload,
            requires_refetch=["/api/v1/lightning-currents/distributions"],
            dedupe_key=f"{event_name}:{payload.get('backfill_task_id', payload.get('line_id', 'unknown'))}",
        )
    except Exception:
        pass


@celery_app.task(
    name="app.tasks.lightning_tasks.prepare_line_lightning_density_job",
    bind=True,
    queue="celery",
    max_retries=1,
    default_retry_delay=30,
    acks_late=True,
    soft_time_limit=1200,
    time_limit=1800,
)
def prepare_line_lightning_density_job(
    self,
    line_id: str,
    distribution_id: str | None = None,
    radius_km: float | None = None,
    region_id: str | None = None,
    years: float | None = None,
    backfill_task_id: str | None = None,
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    """
    异步执行线路地闪密度回填（API 已提前创建 pending 回填任务并派发本任务）。

    流程：标记 processing → 复用 LightningDensityBackfillTask 记录执行计算 →
    推送 started / completed / failed 事件。计算逻辑复用
    services.lightning_service._execute_line_lightning_density_backfill。
    """
    task_id = self.request.id
    log_parts: list[str] = [f"[{task_id}] 开始线路地闪密度回填：线路ID={line_id}"]

    db: Session = SessionLocal()
    backfill_task: LightningDensityBackfillTask | None = None
    try:
        from ..schemas.lightning import LightningDensityPreparationRequest
        from ..services.lightning_service import _execute_line_lightning_density_backfill

        line = db.execute(select(Line).where(Line.id == line_id)).scalar_one_or_none()
        log_parts.append(
            f"[{task_id}] 线路信息：编号={line.code if line else 'N/A'}，名称={line.name if line else 'N/A'}"
            if line
            else f"[{task_id}] 线路未找到：{line_id}"
        )

        if backfill_task_id:
            backfill_task = db.execute(
                select(LightningDensityBackfillTask).where(LightningDensityBackfillTask.id == backfill_task_id)
            ).scalar_one_or_none()
            if backfill_task:
                backfill_task.status = "processing"
                backfill_task.progress = 10
                backfill_task.task_id = task_id
                db.commit()
                log_parts.append(f"[{task_id}] 回填任务记录已更新为 processing（ID={backfill_task_id}）")

        _append_log(log_parts, task_id,
            f"[{task_id}] 回填参数：distribution_id={distribution_id}，radius_km={radius_km}，"
            f"region_id={region_id}，years={years}")
        _publish_density_backfill_event("density_backfill.started", {
            "backfill_task_id": backfill_task_id or "",
            "line_id": line_id,
            "task_id": task_id,
            "status": "processing",
            "progress": 10,
        })

        payload = LightningDensityPreparationRequest(
            line_id=line_id,
            distribution_id=distribution_id,
            radius_km=radius_km,
            region_id=region_id,
            years=years,
        )
        log_parts.append(f"[{task_id}] 开始执行地闪密度回填计算（解析落雷→逐塔统计→渲染沿线圆图）...")
        result = _execute_line_lightning_density_backfill(
            db,
            payload,
            backfill_task_id=backfill_task_id,
            actor_user_id=actor_user_id or "system",
        )
        log_parts.append(
            f"[{task_id}] 回填计算完成：更新杆塔数={result.updated_tower_count}，"
            f"缺少经纬度塔数={result.missing_geo_count}，"
            f"平均Ng={result.avg_density}，min={result.min_density}，max={result.max_density}，"
            f"警告数={result.warning_count}"
        )
        if result.warnings:
            for warning in result.warnings[:10]:
                log_parts.append(f"[{task_id}] 回填警告：{warning}")
        _upload_log(task_id, log_parts)

        has_circle_image = bool(
            backfill_task
            and backfill_task.circle_image_object_key
        )
        _publish_density_backfill_event("density_backfill.completed", {
            "backfill_task_id": backfill_task_id or "",
            "line_id": line_id,
            "task_id": task_id,
            "status": "completed",
            "progress": 100,
            "updated_tower_count": result.updated_tower_count,
            "missing_geo_count": result.missing_geo_count,
            "avg_density": result.avg_density,
            "min_density": result.min_density,
            "max_density": result.max_density,
            "has_circle_image": has_circle_image,
            "warning_count": result.warning_count,
            "warnings": result.warnings[:50],
        })
        return {
            "status": "completed",
            "line_id": line_id,
            "backfill_task_id": backfill_task_id,
            "updated_tower_count": result.updated_tower_count,
            "has_circle_image": has_circle_image,
        }

    except Exception as exc:
        import traceback

        db.rollback()
        _append_log(log_parts, task_id, f"[{task_id}] 回填失败：{exc}")
        _append_log(log_parts, task_id, f"[{task_id}] 异常堆栈：{traceback.format_exc()}")
        _upload_log(task_id, log_parts)
        try:
            if backfill_task_id:
                failed_task = db.execute(
                    select(LightningDensityBackfillTask).where(LightningDensityBackfillTask.id == backfill_task_id)
                ).scalar_one_or_none()
                if failed_task:
                    failed_task.status = "failed"
                    failed_task.error_message = str(exc)
                    db.commit()
            _publish_density_backfill_event("density_backfill.failed", {
                "backfill_task_id": backfill_task_id or "",
                "line_id": line_id,
                "task_id": task_id,
                "status": "failed",
                "error": str(exc),
            })
        except Exception:
            db.rollback()
        return {"status": "failed", "line_id": line_id, "backfill_task_id": backfill_task_id, "error": str(exc)}

    finally:
        db.close()
