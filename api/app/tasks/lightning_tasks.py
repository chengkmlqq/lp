from __future__ import annotations

from typing import Any

from sqlalchemy import select, func as sa_func
from sqlalchemy.orm import Session

from ..core.celery_app import celery_app
from ..core.database import SessionLocal
from ..models.line import Line
from ..models.line_tower import LineTower
from ..models.lightning_amplitude import LightningAmplitude
from ..models.lightning_distribution import LightningDistribution
from ..services.lightning_service import (
    LIGHTNING_AMPLITUDE_TOPIC,
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
            f"[{task_id}] Parsed {len(strikes)} strikes, skipped={skipped_count}, "
            f"warnings={len(warnings)}"
        )

        # ---- 4. 统计 ----
        stats = lightning_statistics.compute_statistics(
            strikes,
            grid_size_km=float(dist.grid_size_km or 1.0),
            data_years=1.0,
            # grid_cells 是纯内部计算的网格聚合明细（20 万格可占约 185MB），
            # 无 API/前端消费者，密度图由 render_density_image 从落点独立重聚合，
            # 故统计阶段不构建，避免巨大瞬时内存与序列化开销。
            include_grid_cells=False,
        )
        dist.area_km2 = stats["area_km2"]
        dist.data_years = stats["data_years"]
        dist.overall_ng = stats["overall_ng"]
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
            data_years=float(dist.data_years or 1.0),
            title=dist.source_file_name,
        )
        if png:
            image_key = minio_storage.build_image_key(dist.id)
            minio_storage.put_object(image_key, png, content_type="image/png")
            dist.image_object_key = image_key
            dist.lp_image_object_key = None  # 重新导入后旧 LP 分区图失效
            _append_log(log_parts, task_id, f"[{task_id}] Image uploaded to {image_key}")
        else:
            _append_log(log_parts, task_id, f"[{task_id}] matplotlib unavailable, skip image rendering")

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
    log_parts = [f"[{task_id}] Starting LP density draw: dist={distribution_id} line={line_id}"]

    db: Session = SessionLocal()
    try:
        from ..services import minio_storage
        from ..services import lightning_statistics

        dist = db.execute(
            select(LightningDistribution).where(LightningDistribution.id == distribution_id)
        ).scalar_one_or_none()
        if not dist:
            _upload_log(task_id, log_parts); return {"status": "failed", "error": "distribution not found"}
        if dist.status != "completed":
            _upload_log(task_id, log_parts); return {"status": "failed", "error": "distribution not completed"}
        # 持久化绘图任务 task_id，供刷新页面后追溯绘图日志（LP-261）
        dist.lp_draw_task_id = task_id
        db.commit()

        line = db.execute(select(Line).where(Line.id == line_id)).scalar_one_or_none()
        if not line:
            _upload_log(task_id, log_parts); return {"status": "failed", "error": "line not found"}

        group_size, radius_km_resolved, _ = _resolve_params_for_voltage(line.voltage_kv)
        if radius_km is not None:
            radius_km_resolved = radius_km

        towers = db.execute(
            select(LineTower).where(LineTower.line_id == line.id)
            .order_by(LineTower.seq_no.asc(), LineTower.id.asc())
        ).scalars().all()
        geo = [t for t in towers if t.longitude is not None and t.latitude is not None]
        if not geo:
            _upload_log(task_id, log_parts); return {"status": "failed", "error": "no geo towers"}

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
            _upload_log(task_id, log_parts); return {"status": "failed", "error": "no strikes"}

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
            _upload_log(task_id, log_parts); return {"status": "failed", "error": "no strikes in bbox"}

        data_years = max(float(dist.data_years or 1.0), 1e-6)
        cells = lightning_statistics.compute_lp_voronoi_cells(groups, radius_km_resolved)
        if not cells:
            _upload_log(task_id, log_parts); return {"status": "failed", "error": "no voronoi cells"}

        png = lightning_statistics.render_lp_density_image(
            strikes, cells, data_years=data_years, radius_km=radius_km_resolved, title=line.name,
        )
        if not png:
            _upload_log(task_id, log_parts); return {"status": "failed", "error": "matplotlib unavailable"}

        build_key = f"lightning/dist/lp/{distribution_id}/{task_id}.png"
        minio_storage.put_object(build_key, png, content_type="image/png")
        dist.lp_image_object_key = build_key
        dist.update_user = actor_user_id
        db.commit()
        _publish_distribution_event("distribution.lp_draw_completed", {
            "distribution_id": dist.id, "status": "completed", "has_lp_image": True,
        })
        _upload_log(task_id, log_parts)
        return {"status": "completed", "distribution_id": dist.id}

    except Exception as exc:
        db.rollback()
        import traceback
        _append_log(log_parts, task_id, f"[{task_id}] FAILED: {exc}")
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
        _publish_amplitude_event("amplitude.import_started", {
            "amplitude_id": amp.id,
            "status": amp.status,
            "progress": amp.progress,
        })

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
        _publish_amplitude_event("amplitude.import_progress", {
            "amplitude_id": amp.id,
            "progress": 30,
        })
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
        _publish_amplitude_event("amplitude.import_progress", {
            "amplitude_id": amp.id,
            "progress": 70,
        })

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
                _publish_amplitude_event("amplitude.import_failed", {
                    "amplitude_id": amp.id,
                    "error": str(exc),
                })
        except Exception:
            db.rollback()
        raise

    finally:
        db.close()
