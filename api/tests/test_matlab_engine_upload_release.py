from __future__ import annotations

import io
import unittest
import zipfile
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.services import fault_matlab_engine_service as svc

MODULE_SLUG = "wave_demo"


def _build_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _make_zip(content: str = "hello") -> bytes:
    """构造包含必需文件的合法 ZIP（内容可调以产生不同 hash）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("RunWaveAnalysisModule", f"#!/bin/sh\necho {content}\n".encode("utf-8"))
        zf.writestr("run_RunWaveAnalysisModule.sh", b"#!/bin/sh\n")
    return buf.getvalue()


class MatlabEngineUploadReleaseTest(unittest.TestCase):
    """上传即发布（无草稿）链路：upload_release + trigger_sync_for_version。"""

    def setUp(self) -> None:
        self.db = _build_session()
        svc.create_module(self.db, {
            "slug": MODULE_SLUG,
            "name": "波形判别模块",
            "worker_deploy_path": "/app/matlab-wave",
        }, actor_user_id="u1")
        self.patches = [
            patch.object(
                svc,
                "_upload_release_package",
                side_effect=lambda _db, _module, _data, _hash, _tag, _log, _by, _by_name: [
                    "RunWaveAnalysisModule",
                    "run_RunWaveAnalysisModule.sh",
                ],
            ),
            patch.object(svc, "_publish_event"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()
        self.db.close()

    def test_upload_release_creates_released_version_directly(self) -> None:
        release = svc.upload_release(
            self.db,
            MODULE_SLUG,
            _make_zip("a"),
            version_tag="v1.0.0",
            changelog="首次发布",
            uploaded_by="u1",
            uploaded_by_name="admin",
        )
        self.assertEqual(release["version_tag"], "v1.0.0")
        self.assertEqual(release["changelog"], "首次发布")
        self.assertEqual(release["uploaded_by_name"], "admin")
        versions = svc._load_versions(self.db, MODULE_SLUG)
        # 无草稿：直接进入 releases
        self.assertIsNone(versions["draft"])
        self.assertEqual(len(versions["releases"]), 1)
        self.assertEqual(versions["releases"][0]["version_hash"], release["version_hash"])

    def test_upload_release_requires_version_tag(self) -> None:
        with self.assertRaises(svc.MatlabEngineError):
            svc.upload_release(
                self.db,
                MODULE_SLUG,
                _make_zip("b"),
                version_tag="  ",
                changelog="",
                uploaded_by="u1",
            )

    def test_upload_release_rejects_duplicate_version_tag(self) -> None:
        svc.upload_release(
            self.db, MODULE_SLUG, _make_zip("c"), version_tag="v1.0.0", changelog="", uploaded_by="u1",
        )
        with self.assertRaises(svc.MatlabEngineError):
            svc.upload_release(
                self.db, MODULE_SLUG, _make_zip("d"), version_tag="v1.0.0", changelog="", uploaded_by="u1",
            )

    def test_upload_release_rejects_duplicate_hash(self) -> None:
        data = _make_zip("same")
        svc.upload_release(
            self.db, MODULE_SLUG, data, version_tag="v1.0.0", changelog="", uploaded_by="u1",
        )
        with self.assertRaises(svc.MatlabEngineError):
            svc.upload_release(
                self.db, MODULE_SLUG, data, version_tag="v1.0.1", changelog="", uploaded_by="u1",
            )

    @patch("app.tasks.sync_matlab_engine_task.sync_matlab_engine_module.delay")
    def test_trigger_sync_for_version_dispatches_target_version(self, delay) -> None:
        svc.upload_release(
            self.db, MODULE_SLUG, _make_zip("x"), version_tag="v1.0.0", changelog="", uploaded_by="u1",
        )
        svc.upload_release(
            self.db, MODULE_SLUG, _make_zip("y"), version_tag="v2.0.0", changelog="", uploaded_by="u1",
        )
        releases = svc._load_versions(self.db, MODULE_SLUG)["releases"]
        # 生效旧版本（v1.0.0）
        target = releases[1]
        delay.return_value.id = "task-123"
        task_id = svc.trigger_sync_for_version(
            self.db, MODULE_SLUG, target["version_hash"], actor_user_id="u1",
        )
        self.assertEqual(task_id, "task-123")
        delay.assert_called_once_with(
            MODULE_SLUG,
            target["version_hash"],
            "/app/matlab-wave",
            "u1",
        )

    def test_trigger_sync_for_version_unknown_version_raises(self) -> None:
        with self.assertRaises(svc.MatlabEngineError):
            svc.trigger_sync_for_version(
                self.db, MODULE_SLUG, "nope999", actor_user_id="u1",
            )


if __name__ == "__main__":
    unittest.main()
