"""防雷改造 —— 高杆塔雷击成因分析数据源。

前端页面 `web/src/app/admin/lightning-retrofit/high-risk-reason/page.tsx`
按线路查询「高风险杆塔 + 成因」，但 LP-486 引入该前端页时后端端点未同步实现，
页面请求一直 404（详见缺陷 1）。本模块补齐该端点。

口径：
  取该线路下**最近一个已产出杆塔结果**的任务，返回其中高风险的杆塔结果，
  按塔序 `seq_no` 升序分页。

  仅取最新一轮 run 的结果——`fl_analysis_tower_result` 同一 run 内同塔唯一
  （见模型 UniqueConstraint），但历史 run 会留存旧结果，若不过滤会出现同一
  杆塔重复行。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route
from ...models.fl_analysis import FlAnalysisJob, FlAnalysisTowerResult, FlAnalysisTowerSnapshot
from ...schemas.fl_analysis import FlAnalysisTowerResultListResponse
from ...services.fl_analysis_service import serialize_tower_result

router = APIRouter(
    prefix="/lightning-retrofit",
    tags=["lightning-retrofit"],
    dependencies=[Depends(require_enabled_menu_route)],
)

# 高风险口径：现行 risk_level 为 low/medium/high；同时兼容历史数值口径（3/4）
_HIGH_RISK_LEVELS: tuple[str, ...] = ("high", "3", "4")


def _latest_job_with_results(db: Session, line_id: str) -> FlAnalysisJob | None:
    """取该线路下最近一个「已产出杆塔结果」的任务。

    线路下的任务可能包含尚未执行（pending/queued）或执行失败无结果的任务，
    因此按创建时间倒序找到第一个真正有结果行的任务。
    """
    jobs = (
        db.execute(
            select(FlAnalysisJob)
            .where(FlAnalysisJob.line_id == line_id)
            .order_by(FlAnalysisJob.create_date.desc())
        )
        .scalars()
        .all()
    )
    for job in jobs:
        produced = db.scalar(
            select(func.count())
            .select_from(FlAnalysisTowerResult)
            .where(FlAnalysisTowerResult.job_id == job.id)
        )
        if produced:
            return job
    return None


@router.get("/high-risk-reason", response_model=FlAnalysisTowerResultListResponse)
def list_high_risk_reason(
    line_id: str = Query(..., min_length=1, description="线路 ID"),
    limit: int = Query(default=20, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission("line.read", "line.manage")),
    db: Session = Depends(get_db),
) -> FlAnalysisTowerResultListResponse:
    """按线路返回高风险杆塔及其成因（供「高杆塔雷击成因分析」页表格使用）。"""
    job = _latest_job_with_results(db, line_id)
    if job is None:
        return FlAnalysisTowerResultListResponse(items=[], total=0)

    conditions = [
        FlAnalysisTowerResult.job_id == job.id,
        FlAnalysisTowerResult.risk_level.in_(_HIGH_RISK_LEVELS),
    ]
    if job.latest_run_id:
        conditions.append(FlAnalysisTowerResult.run_id == job.latest_run_id)

    total = int(
        db.scalar(select(func.count()).select_from(FlAnalysisTowerResult).where(*conditions)) or 0
    )
    rows = (
        db.execute(
            select(FlAnalysisTowerResult)
            .join(
                FlAnalysisTowerSnapshot,
                FlAnalysisTowerSnapshot.id == FlAnalysisTowerResult.snapshot_id,
            )
            .where(*conditions)
            # 按杆塔序号正序，与任务详情页杆塔列表口径一致
            .order_by(FlAnalysisTowerSnapshot.seq_no.asc())
            .offset(offset)
            .limit(limit)
            .options(selectinload(FlAnalysisTowerResult.snapshot))
        )
        .scalars()
        .all()
    )

    return FlAnalysisTowerResultListResponse(
        items=[serialize_tower_result(row) for row in rows],
        total=total,
    )
