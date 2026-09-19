"""把 92 塔同跳任务拆成 4 个并行子任务（各 23 塔），利用 wine-worker concurrency=4。

以模板任务的参数为基础，将其 selected_tower_ids 均分成 4 组，每组用相同
execution_options/line/job_type 创建独立任务并启动 —— 各占一个 worker 进程，
4 个任务并行，整体 92 塔从串行 ~24h 缩到约 ~6h。

用法（在 api 容器内执行）：
    python3 scripts/split_fl_job.py [模板任务ID]

模板任务 ID 也可通过环境变量 FL_TEMPLATE_JOB_ID 指定；不传则用下面的历史默认值。
"""
from __future__ import annotations

import os
import sys

from app.core.database import SessionLocal
from app.models.user import User
from app.schemas.fl_analysis import FlAnalysisJobCreateRequest
from app.services.fl_analysis_service import create_job, get_job_by_id, start_job

# 历史默认模板（该任务可能已删除，建议用 CLI 参数/环境变量显式指定）
TEMPLATE_JOB_ID = os.environ.get("FL_TEMPLATE_JOB_ID") or (
    sys.argv[1] if len(sys.argv) > 1 else "1381af97b858451286272772c4079826"
)
ACTOR_USER_ID = "admin"
SPLIT = 4
NAME_TMPL = "500源上-根治重跑-分片{i}/{n}"


def main() -> None:
    db = SessionLocal()
    try:
        src = get_job_by_id(db, TEMPLATE_JOB_ID)
        if not src:
            raise SystemExit(f"模板任务未找到: {TEMPLATE_JOB_ID}")
        opts = dict(src.execution_options_json or {})
        towers = list(opts.get("selected_tower_ids") or [])
        if len(towers) != 92:
            print(f"提示: selected_tower_ids 共 {len(towers)} 个（期望 92）")
        if not towers:
            raise SystemExit("模板任务无 selected_tower_ids，无法拆分")

        actor = db.query(User).filter(User.id == ACTOR_USER_ID).first()
        if actor is None:
            actor = db.query(User).filter(User.status == "ENABLED").first()
        if actor is None:
            raise SystemExit("无可用的 actor 用户")

        # 均分 4 组
        n = len(towers)
        base = n // SPLIT
        extra = n % SPLIT
        groups = []
        idx = 0
        for i in range(SPLIT):
            size = base + (1 if i < extra else 0)
            groups.append(towers[idx:idx + size])
            idx += size

        created = []
        for i, grp in enumerate(groups, start=1):
            sub_opts = dict(opts)
            sub_opts["selected_tower_ids"] = grp
            payload = FlAnalysisJobCreateRequest(
                line_id=src.line_id,
                job_name=NAME_TMPL.format(i=i, n=SPLIT),
                job_type=src.job_type,
                external_adapter=src.external_adapter,
                adapter_config_json=src.adapter_config_json,
                execution_options_json=sub_opts,
            )
            c = create_job(db, payload, actor=actor)
            db.commit()
            s = start_job(db, job_id=c.job.id, actor=actor)
            db.commit()
            created.append((c.job.id, len(grp)))
            print(f"分片{i}: 任务={c.job.id} 塔数={len(grp)} status={s.job.status}")

        print(f"\n共创建并启动 {len(created)} 个并行任务，总塔数 {sum(g for _, g in created)}")
    finally:
        db.close()


if __name__ == "__main__":
    main()