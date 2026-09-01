from __future__ import annotations

import sys
import unittest
from types import ModuleType
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.fault_analysis import FaultAnalysis
from app.services import fault_analysis_service as svc


def _build_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


class FaultAnalysisTaskIdTest(unittest.TestCase):
    """LP 增强：判别任务派发时把 Celery task_id 记录到故障分析记录，供页面追溯执行日志。"""

    @classmethod
    def setUpClass(cls) -> None:
        # dispatch_fault_diagnosis 内延迟导入 app.tasks.fault_diagnosis_tasks，
        # 测试环境无 celery，用假模块替换，避免引入 Celery 依赖。
        cls.task_patcher = MagicMock()
        fake_module = ModuleType("app.tasks.fault_diagnosis_tasks")
        fake_module.run_fault_diagnosis_task = cls.task_patcher
        sys.modules["app.tasks.fault_diagnosis_tasks"] = fake_module

    @classmethod
    def tearDownClass(cls) -> None:
        sys.modules.pop("app.tasks.fault_diagnosis_tasks", None)

    def setUp(self) -> None:
        self.db = _build_session()
        self.item = FaultAnalysis(
            id="abc123",
            title="测试分析",
            status="pending",
        )
        self.db.add(self.item)
        self.db.commit()
        # reset_mock 默认不重置 side_effect/return_value，必须显式重置，
        # 避免上个用例设置的 delay.side_effect 泄漏到本用例。
        self.task_patcher.reset_mock(return_value=True, side_effect=True)

    def tearDown(self) -> None:
        self.db.close()

    def test_dispatch_records_task_id(self) -> None:
        async_result = MagicMock()
        async_result.id = "celery-task-001"
        self.task_patcher.delay.return_value = async_result

        svc.dispatch_fault_diagnosis(self.db, "abc123")

        self.task_patcher.delay.assert_called_once_with("abc123")
        self.db.refresh(self.item)
        self.assertEqual(self.item.task_id, "celery-task-001")
        self.assertEqual(self.item.status, "processing")

    def test_dispatch_failure_marks_failed(self) -> None:
        self.task_patcher.delay.side_effect = RuntimeError("broker down")

        svc.dispatch_fault_diagnosis(self.db, "abc123")

        self.db.refresh(self.item)
        self.assertEqual(self.item.status, "failed")
        self.assertIn("判别任务派发失败", self.item.result_json["error"]["message"])
        # 派发失败时不应残留 task_id
        self.assertIsNone(self.item.task_id)


if __name__ == "__main__":
    unittest.main()
