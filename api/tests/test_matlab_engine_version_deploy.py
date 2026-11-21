from __future__ import annotations

import unittest
from datetime import datetime, timezone
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


def _seed_versions(db) -> None:
    """直接写入两个已发布版本（绕过上传/发布链路，避免依赖 MinIO）。"""
    svc._save_versions(db, MODULE_SLUG, {
        "draft": None,
        "releases": [
            {
                "version_hash": "aaa111",
                "version_tag": "v1.0.0",
                "changelog": "",
                "uploaded_by": "u1",
                "uploaded_by_name": "admin",
                "upload_time": "2026-01-01T00:00:00+00:00",
                "size_bytes": 100,
                "file_list": [],
            },
            {
                "version_hash": "bbb222",
                "version_tag": "v2.0.0",
                "changelog": "",
                "uploaded_by": "u1",
                "uploaded_by_name": "admin",
                "upload_time": "2026-01-02T00:00:00+00:00",
                "size_bytes": 200,
                "file_list": [],
            },
        ],
    })


class MatlabEngineVersionDeployTest(unittest.TestCase):
    """LP 增强：标记“Worker 当前生效版本”（is_active / deployed_at）。"""

    def setUp(self) -> None:
        self.db = _build_session()
        svc.create_module(self.db, {
            "slug": MODULE_SLUG,
            "name": "波形判别模块",
            "worker_deploy_path": "/app/matlab-wave",
        }, actor_user_id="u1")
        _seed_versions(self.db)
        # 测试环境无 MinIO，屏蔽会触网的服务调用
        self.patches = [
            patch.object(svc, "_load_manifest", return_value=None),
            patch.object(svc, "_copy_package"),
            patch.object(svc, "_write_manifest"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()
        self.db.close()

    @staticmethod
    def _by_hash(releases: list[dict]) -> dict[str, dict]:
        return {r["version_hash"]: r for r in releases}

    def test_mark_deployed_sets_active_and_clears_others(self) -> None:
        ok = svc.mark_version_deployed(self.db, MODULE_SLUG, "bbb222")
        self.assertTrue(ok)
        releases = self._by_hash(svc._load_versions(self.db, MODULE_SLUG)["releases"])
        self.assertTrue(releases["bbb222"]["is_active"])
        self.assertIn("deployed_at", releases["bbb222"])
        self.assertFalse(releases["aaa111"]["is_active"])
        self.assertNotIn("deployed_at", releases["aaa111"])

    def test_mark_deployed_unknown_hash_returns_false(self) -> None:
        ok = svc.mark_version_deployed(self.db, MODULE_SLUG, "nope999")
        self.assertFalse(ok)
        releases = svc._load_versions(self.db, MODULE_SLUG)["releases"]
        self.assertTrue(all(not r.get("is_active") for r in releases))

    def test_mark_deployed_unknown_module_no_error(self) -> None:
        # 模块不存在时 _load_versions 返回空结构，标记应安全返回 False
        ok = svc.mark_version_deployed(self.db, "missing_module", "aaa111")
        self.assertFalse(ok)

    def test_list_versions_normalizes_active_flag(self) -> None:
        svc.mark_version_deployed(self.db, MODULE_SLUG, "aaa111")
        releases = self._by_hash(svc.list_versions(self.db, MODULE_SLUG)["releases"])
        self.assertTrue(releases["aaa111"]["is_active"])
        self.assertFalse(releases["bbb222"]["is_active"])
        self.assertNotIn("deployed_at", releases["bbb222"])
        # 已部署版本自身带部署时间
        self.assertIn("deployed_at", releases["aaa111"])

    def test_list_versions_all_inactive_when_none_marked(self) -> None:
        releases = svc.list_versions(self.db, MODULE_SLUG)["releases"]
        self.assertTrue(all(r["is_active"] is False for r in releases))
        self.assertTrue(all("deployed_at" not in r for r in releases))

    def test_list_versions_pagination_keeps_active_on_own_page(self) -> None:
        svc.mark_version_deployed(self.db, MODULE_SLUG, "aaa111")
        page1 = svc.list_versions(self.db, MODULE_SLUG, limit=1, offset=0)["releases"]
        self.assertEqual(len(page1), 1)
        self.assertTrue(page1[0]["is_active"])
        page2 = svc.list_versions(self.db, MODULE_SLUG, limit=1, offset=1)["releases"]
        self.assertEqual(len(page2), 1)
        self.assertFalse(page2[0]["is_active"])

    def test_publish_does_not_inherit_deploy_marker(self) -> None:
        svc.mark_version_deployed(self.db, MODULE_SLUG, "aaa111")
        versions = svc._load_versions(self.db, MODULE_SLUG)
        # 直接构造一个携带部署标记的草稿（即使回退逻辑漏删，发布也不应继承）
        draft = dict(versions["releases"][0])  # aaa111 为已部署版本
        draft["version_tag"] = ""
        draft["changelog"] = ""
        versions["draft"] = draft
        svc._save_versions(self.db, MODULE_SLUG, versions)

        release = svc.publish_draft(
            self.db,
            MODULE_SLUG,
            draft["version_hash"],
            "v9.9.9",
            "changelog",
            actor_user_id="u1",
        )
        self.assertFalse(release.get("is_active"))
        self.assertNotIn("deployed_at", release)

        releases = svc.list_versions(self.db, MODULE_SLUG)["releases"]
        new_release = releases[0]
        self.assertEqual(new_release["version_tag"], "v9.9.9")
        self.assertFalse(new_release["is_active"])
        # 已部署标记仍停留在原来那个版本记录上（同 hash 的新发布不继承）
        active = [r for r in releases if r["is_active"]]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["version_tag"], "v1.0.0")

    def test_rollback_does_not_inherit_deploy_marker(self) -> None:
        svc.mark_version_deployed(self.db, MODULE_SLUG, "aaa111")
        draft = svc.rollback_to_version(self.db, MODULE_SLUG, "aaa111", actor_user_id="u1")
        self.assertFalse(draft.get("is_active"))
        self.assertNotIn("deployed_at", draft)
        # releases 中的已部署标记不受回退影响
        releases = self._by_hash(svc._load_versions(self.db, MODULE_SLUG)["releases"])
        self.assertTrue(releases["aaa111"]["is_active"])

    def test_duplicate_hash_releases_only_first_marked(self) -> None:
        # 回退后重新发布会产生同 hash 的新旧两条记录：标记时只激活最靠前的一条
        versions = svc._load_versions(self.db, MODULE_SLUG)
        dup = dict(versions["releases"][0])  # 同 hash aaa111 的“新发布”
        dup["version_tag"] = "v9.9.9"
        dup.pop("is_active", None)
        dup.pop("deployed_at", None)
        versions["releases"].insert(0, dup)
        svc._save_versions(self.db, MODULE_SLUG, versions)

        ok = svc.mark_version_deployed(self.db, MODULE_SLUG, "aaa111")
        self.assertTrue(ok)
        releases = svc.list_versions(self.db, MODULE_SLUG)["releases"]
        active = [r for r in releases if r["is_active"]]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["version_tag"], "v9.9.9")


class MatlabEngineSyncStateTest(unittest.TestCase):
    """LP-55：同步进度（pending/running/completed/failed）与部署 worker 记录。"""

    def setUp(self) -> None:
        self.db = _build_session()
        svc.create_module(self.db, {
            "slug": MODULE_SLUG,
            "name": "波形判别模块",
            "worker_deploy_path": "/app/matlab-wave",
        }, actor_user_id="u1")
        _seed_versions(self.db)
        self.patches = [
            patch.object(svc, "_load_manifest", return_value=None),
            patch.object(svc, "_copy_package"),
            patch.object(svc, "_write_manifest"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()
        self.db.close()

    def _sync_state(self, version_hash: str) -> dict:
        versions = svc._load_versions(self.db, MODULE_SLUG)
        target = next(r for r in versions["releases"] if r["version_hash"] == version_hash)
        return target.get("sync_state") or {}

    def test_pending_then_running_then_completed(self) -> None:
        svc.record_sync_state(
            self.db, MODULE_SLUG, "aaa111",
            status="pending", task_id="task-1", queue="matlab-wind",
        )
        state = self._sync_state("aaa111")
        self.assertEqual(state["status"], "pending")
        self.assertEqual(state["task_id"], "task-1")
        self.assertEqual(state["queue"], "matlab-wind")
        self.assertTrue(state.get("requested_at"))

        svc.record_sync_state(
            self.db, MODULE_SLUG, "aaa111",
            status="running", task_id="task-1", worker="matlab-wind@ctyun-local",
        )
        state = self._sync_state("aaa111")
        self.assertEqual(state["status"], "running")
        self.assertEqual(state["worker"], "matlab-wind@ctyun-local")
        self.assertTrue(state.get("started_at"))

        # 完成时同时记录部署目标 worker
        svc.mark_version_deployed(self.db, MODULE_SLUG, "aaa111", worker="matlab-wind@ctyun-local")
        svc.record_sync_state(
            self.db, MODULE_SLUG, "aaa111",
            status="completed", task_id="task-1", worker="matlab-wind@ctyun-local",
        )
        state = self._sync_state("aaa111")
        self.assertEqual(state["status"], "completed")
        self.assertTrue(state.get("finished_at"))
        self.assertNotIn("error", state)

        releases = {r["version_hash"]: r for r in svc.list_versions(self.db, MODULE_SLUG)["releases"]}
        self.assertTrue(releases["aaa111"]["is_active"])
        self.assertEqual(releases["aaa111"]["deployed_worker"], "matlab-wind@ctyun-local")

    def test_failed_keeps_error_text(self) -> None:
        svc.record_sync_state(
            self.db, MODULE_SLUG, "bbb222",
            status="failed", task_id="task-2", error="deploy failed: disk full",
        )
        state = self._sync_state("bbb222")
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["error"], "deploy failed: disk full")

    def test_new_pending_clears_previous_failure(self) -> None:
        svc.record_sync_state(
            self.db, MODULE_SLUG, "bbb222", status="failed", task_id="t-old", error="boom",
        )
        svc.record_sync_state(
            self.db, MODULE_SLUG, "bbb222", status="pending", task_id="t-new", queue="matlab-wind",
        )
        state = self._sync_state("bbb222")
        self.assertEqual(state["status"], "pending")
        self.assertEqual(state["task_id"], "t-new")
        self.assertNotIn("error", state)
        self.assertNotIn("finished_at", state)

    def test_record_sync_state_unknown_version_returns_false(self) -> None:
        ok = svc.record_sync_state(self.db, MODULE_SLUG, "nope999", status="pending")
        self.assertFalse(ok)

    def test_list_versions_hides_deployed_worker_for_inactive(self) -> None:
        svc.mark_version_deployed(self.db, MODULE_SLUG, "aaa111", worker="matlab-wind@ctyun-local")
        svc.mark_version_deployed(self.db, MODULE_SLUG, "bbb222", worker="matlab-worker@matlab-local")
        releases = {r["version_hash"]: r for r in svc.list_versions(self.db, MODULE_SLUG)["releases"]}
        self.assertEqual(releases["bbb222"]["deployed_worker"], "matlab-worker@matlab-local")
        self.assertNotIn("deployed_worker", releases["aaa111"])


class MatlabEngineQueueWorkersTest(unittest.TestCase):
    """LP-55：按队列聚合在线 worker（复用 Flower 快照，不可用时降级）。"""

    @staticmethod
    def _overview():
        from app.schemas.flower_monitor import FlowerWorkerItem, FlowerWorkersOverviewResponse

        return FlowerWorkersOverviewResponse(
            generated_at=datetime.now(timezone.utc),
            workers=[
                FlowerWorkerItem(worker="matlab-wind@ctyun-local", status="ONLINE", queue_names=["matlab-wind"]),
                FlowerWorkerItem(worker="matlab-worker@matlab-local", status="ONLINE", queue_names=["matlab-diagnostics"]),
                FlowerWorkerItem(worker="stale@host", status="OFFLINE", queue_names=["matlab-wind"]),
            ],
        )

    def test_aggregates_online_workers_by_queue(self) -> None:
        with patch(
            "app.services.flower_monitor_service.build_workers_overview",
            return_value=self._overview(),
        ):
            data = svc.list_queue_workers()
        self.assertTrue(data["available"])
        queues = {item["queue"]: item for item in data["queues"]}
        self.assertEqual(queues["matlab-wind"]["online"], 1)
        self.assertEqual(queues["matlab-wind"]["workers"], ["matlab-wind@ctyun-local"])
        self.assertEqual(queues["matlab-diagnostics"]["online"], 1)

    def test_degrades_when_flower_unavailable(self) -> None:
        with patch(
            "app.services.flower_monitor_service.build_workers_overview",
            side_effect=RuntimeError("flower down"),
        ):
            data = svc.list_queue_workers()
        self.assertFalse(data["available"])
        self.assertEqual(data["queues"], [])


class MatlabEngineZipValidationTest(unittest.TestCase):
    """LP-55：缺必需文件时提示缺失文件名，并给出 main_angle 无后缀产物的排查指引。"""

    def test_missing_required_file_message_mentions_file_and_hint(self) -> None:
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("main_angle", b"binary")
        ok, message = svc._validate_zip_content(buf.getvalue(), ["main_angle.exe"])
        self.assertFalse(ok)
        self.assertIn("main_angle.exe", message)
        self.assertIn("main_angle", message)
        self.assertIn("必需文件", message)

    def test_valid_zip_with_linux_executable_passes(self) -> None:
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("main_angle", b"binary")
        ok, message = svc._validate_zip_content(buf.getvalue(), ["main_angle"])
        self.assertTrue(ok)
        self.assertEqual(message, "")


if __name__ == "__main__":
    unittest.main()
