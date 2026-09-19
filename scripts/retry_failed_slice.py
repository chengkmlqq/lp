"""重建失败的分片任务（按指定失败任务的相同参数）。

用法（在 api 容器内执行）：
    python3 scripts/retry_failed_slice.py [失败任务ID] [新任务名]

失败任务 ID 也可通过环境变量 FL_FAILED_JOB_ID 指定；不传则用下面的历史默认值。
"""
from __future__ import annotations

import os
import sys

from app.core.database import SessionLocal
from app.models.user import User
from app.schemas.fl_analysis import FlAnalysisJobCreateRequest
from app.services.fl_analysis_service import create_job, get_job_by_id, start_job

FAILED_SLICE_ID = os.environ.get("FL_FAILED_JOB_ID") or (
    sys.argv[1] if len(sys.argv) > 1 else "430bce90a2a3464c9fbb8e4e8ea308cd"
)
ACTOR_USER_ID = "admin"
NEW_JOB_NAME = (sys.argv[2] if len(sys.argv) > 2 else "") or "500源上-根治重跑-分片1/4-重跑"


def main() -> None:
    db = SessionLocal()
    try:
        src = get_job_by_id(db, FAILED_SLICE_ID)
        if not src:
            raise SystemExit(f"失败分片未找到: {FAILED_SLICE_ID}")
        opts = dict(src.execution_options_json or {})
        towers = list(opts.get("selected_tower_ids") or [])
        actor = db.query(User).filter(User.id == ACTOR_USER_ID).first()
        if actor is None:
            actor = db.query(User).filter(User.status == "ENABLED").first()
        if actor is None:
            raise SystemExit("无可用的 actor 用户")

        payload = FlAnalysisJobCreateRequest(
            line_id=src.line_id,
            job_name=NEW_JOB_NAME,
            job_type=src.job_type,
            external_adapter=src.external_adapter,
            adapter_config_json=src.adapter_config_json,
            execution_options_json=opts,
        )
        created = create_job(db, payload, actor=actor)
        db.commit()
        started = start_job(db, job_id=created.job.id, actor=actor)
        db.commit()
        print(f"重建并启动: 任务={created.job.id} 塔数={len(towers)} status={started.job.status} task_id={started.job.task_id}")
    finally:
        db.close()


if __name__ == "__main__":
    main()