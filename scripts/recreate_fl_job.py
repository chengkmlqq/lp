"""按指定模板任务的参数重建同跳计算任务并启动。

用法（在 api 容器内执行）：
    python3 scripts/recreate_fl_job.py [模板任务ID] [新任务名]

模板任务 ID 也可通过环境变量 FL_TEMPLATE_JOB_ID 指定；不传则用下面的历史默认值。
"""
from __future__ import annotations

import os
import sys

from app.core.database import SessionLocal
from app.models.user import User
from app.schemas.fl_analysis import FlAnalysisJobCreateRequest
from app.services.fl_analysis_service import (
    create_job,
    get_job_by_id,
    start_job,
)

# 历史默认模板（该任务可能已删除，建议用 CLI 参数/环境变量显式指定）
TEMPLATE_JOB_ID = os.environ.get("FL_TEMPLATE_JOB_ID") or (
    sys.argv[1] if len(sys.argv) > 1 else "4448fa0de21a422ca64462d8634f10b7"
)
ACTOR_USER_ID = "admin"
NEW_JOB_NAME = (sys.argv[2] if len(sys.argv) > 2 else "") or "500源上-根治重跑"


def main() -> None:
    db = SessionLocal()
    try:
        src = get_job_by_id(db, TEMPLATE_JOB_ID)
        if not src:
            raise SystemExit(f"模板任务未找到: {TEMPLATE_JOB_ID}")
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
            execution_options_json=src.execution_options_json,
        )
        created = create_job(db, payload, actor=actor)
        job_id = created.job.id
        db.commit()
        print(f"任务已创建: {job_id} name={NEW_JOB_NAME} type={src.job_type} towers={created.job.total_tower_count}")

        started = start_job(db, job_id=job_id, actor=actor)
        db.commit()
        print(f"任务已启动: 任务id={started.job.id} status={started.job.status} task_id={started.job.task_id}")
    finally:
        db.close()


if __name__ == "__main__":
    main()