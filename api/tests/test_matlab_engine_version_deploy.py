from __future__ import annotations

import unittest
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


if __name__ == "__main__":
    unittest.main()
