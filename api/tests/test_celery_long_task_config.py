from __future__ import annotations

import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("MINIO_ENABLED", "false")

from api.app.core.celery_app import celery_app  # noqa: F401,E402
from api.app.tasks.lightning_tasks import import_lightning_distribution_job  # noqa: F401,E402


class CeleryLongTaskConfigTest(unittest.TestCase):
    """LP-187：重任务超过 Redis visibility_timeout 被重投导致双副本并行。

    校验全局 broker visibility_timeout 已调大、worker 丢失时消息会 reject 回队，
    以及 import_lightning_distribution_job 重任务具备软/硬时间限制兜底。
    """

    def test_broker_visibility_timeout_covers_long_tasks(self) -> None:
        opts = celery_app.conf.broker_transport_options or {}
        # Redis 默认 visibility_timeout=3600s，重任务（约 106 分钟）会超时被重投；
        # 需调大到 21600s（6 小时）覆盖最长任务耗时。
        self.assertEqual(opts.get("visibility_timeout"), 21600)

    def test_task_reject_on_worker_lost_enabled(self) -> None:
        # 配合 acks_late：worker 异常退出时消息 reject 回到队列及时重投，
        # 而不是依赖 visibility_timeout 的漫长等待。
        self.assertIs(celery_app.conf.task_reject_on_worker_lost, True)

    def test_distribution_job_has_time_limits(self) -> None:
        task = import_lightning_distribution_job
        self.assertEqual(task.soft_time_limit, 7200)  # 软限制 2 小时
        self.assertEqual(task.time_limit, 10800)      # 硬限制 3 小时
        self.assertIs(task.acks_late, True)


if __name__ == "__main__":
    unittest.main()
