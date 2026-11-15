"""LP-22 后端语言解析单测：参数取值 / 非法回落 / 任务级优先 / 缓存 / 失效 / 任务快照。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services import backend_lang


@pytest.fixture(autouse=True)
def _reset_cache():
    backend_lang.invalidate_default_lang_cache()
    yield
    backend_lang.invalidate_default_lang_cache()


class TestNormalizeLang:
    def test_valid_values(self):
        assert backend_lang.normalize_lang("zh") == "zh"
        assert backend_lang.normalize_lang("en") == "en"
        assert backend_lang.normalize_lang(" EN ") == "en"
        assert backend_lang.normalize_lang("En") == "en"

    def test_aliases(self):
        assert backend_lang.normalize_lang("zh-CN") == "zh"
        assert backend_lang.normalize_lang("en-US") == "en"

    def test_invalid_falls_back_to_none(self):
        for value in ("fr", "", "   ", None, 1, True, [], "zh-CN-extra"):
            assert backend_lang.normalize_lang(value) is None


def _patch_param(value):
    """把 app.language 的读取打桩到指定明文值。"""
    session = MagicMock()
    return (
        patch("app.core.database.SessionLocal", return_value=session),
        patch("app.services.system_param_service.get_system_param_decrypted", return_value=value),
    )


class TestDefaultLang:
    def test_en_param(self):
        sl, gspd = _patch_param("en")
        with sl, gspd:
            assert backend_lang.get_default_lang() == "en"

    def test_zh_param(self):
        sl, gspd = _patch_param("zh")
        with sl, gspd:
            assert backend_lang.get_default_lang() == "zh"

    def test_invalid_param_falls_back_to_zh(self):
        sl, gspd = _patch_param("fr")
        with sl, gspd:
            assert backend_lang.get_default_lang() == "zh"

    def test_missing_or_disabled_param_falls_back_to_zh(self):
        sl, gspd = _patch_param(None)
        with sl, gspd:
            assert backend_lang.get_default_lang() == "zh"

    def test_db_error_falls_back_to_zh(self):
        with patch("app.core.database.SessionLocal", side_effect=RuntimeError("db down")):
            assert backend_lang.get_default_lang() == "zh"

    def test_cache_reads_db_only_once(self):
        sl, gspd = _patch_param("en")
        with sl, gspd as mocked:
            assert backend_lang.get_default_lang() == "en"
            assert backend_lang.get_default_lang() == "en"
            assert backend_lang.get_default_lang() == "en"
            assert mocked.call_count == 1

    def test_invalidation_forces_reread(self):
        sl, gspd = _patch_param("en")
        with sl, gspd as mocked:
            assert backend_lang.get_default_lang() == "en"
            backend_lang.invalidate_default_lang_cache()
            assert backend_lang.get_default_lang() == "en"
            assert mocked.call_count == 2


class TestResolveBackendLang:
    def test_task_lang_takes_priority_and_skips_global_read(self):
        sl, gspd = _patch_param("zh")
        with sl, gspd as mocked:
            assert backend_lang.resolve_backend_lang("en") == "en"
            assert mocked.call_count == 0

    def test_invalid_task_lang_falls_back_to_global(self):
        sl, gspd = _patch_param("en")
        with sl, gspd:
            assert backend_lang.resolve_backend_lang("fr") == "en"
            assert backend_lang.resolve_backend_lang(None) == "en"

    def test_no_task_lang_uses_global(self):
        sl, gspd = _patch_param("zh")
        with sl, gspd:
            assert backend_lang.resolve_backend_lang() == "zh"


class TestRequestLangContext:
    def test_bind_and_reset(self):
        token = backend_lang.bind_request_lang("en")
        try:
            assert backend_lang.get_request_lang() == "en"
            assert backend_lang.current_backend_lang() == "en"
        finally:
            backend_lang.reset_request_lang(token)
        assert backend_lang.get_request_lang() is None

    def test_invalid_header_is_ignored(self):
        token = backend_lang.bind_request_lang("fr")
        try:
            assert backend_lang.get_request_lang() is None
        finally:
            backend_lang.reset_request_lang(token)


class TestMiddleware:
    def test_sets_request_lang_for_http_scope(self):
        import asyncio

        captured = {}

        async def app(scope, receive, send):
            captured["lang"] = backend_lang.get_request_lang()

        mw = backend_lang.BackendLangMiddleware(app)
        scope = {"type": "http", "headers": [(b"x-lang", b"en"), (b"host", b"localhost")]}
        asyncio.run(mw(scope, None, None))
        assert captured["lang"] == "en"
        assert backend_lang.get_request_lang() is None

    def test_non_http_scope_is_untouched(self):
        import asyncio

        async def app(scope, receive, send):
            assert backend_lang.get_request_lang() is None

        mw = backend_lang.BackendLangMiddleware(app)
        asyncio.run(mw({"type": "websocket", "headers": []}, None, None))


class TestEnsureAppLanguageParam:
    def test_creates_and_is_idempotent(self):
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        from app.core.database import Base
        from app.models.system_param import SystemParam

        engine = create_engine(
            "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        try:
            with Session() as db:
                assert backend_lang.ensure_app_language_param(db) is True
                db.commit()
            with Session() as db:
                assert backend_lang.ensure_app_language_param(db) is False
                row = db.execute(
                    select(SystemParam).where(SystemParam.param_key == "app.language")
                ).scalar_one()
                assert row.param_value == "zh"
                assert row.status == "enabled"
                assert row.is_encrypted is False
        finally:
            Base.metadata.drop_all(bind=engine)
            engine.dispose()


class TestTaskLangSnapshot:
    def test_prerun_snapshots_header_lang(self):
        from app.core import task_history_signals
        from app.core.task_log_capture import TaskLogCapture

        TaskLogCapture._registry.clear()
        fake_request = SimpleNamespace(lp_lang="en", hostname="w1", delivery_info={"routing_key": "q"})
        fake_task = SimpleNamespace(name="app.tasks.demo", request=fake_request)
        try:
            with patch.object(task_history_signals, "_upsert_task"):
                task_history_signals.on_task_prerun(task_id="snap-1", task=fake_task)
            buf = TaskLogCapture.get("snap-1")
            assert buf is not None
            assert buf.lang == "en"
            assert backend_lang.current_backend_lang() == "en"
        finally:
            TaskLogCapture._registry.clear()

    def test_before_task_publish_injects_request_lang(self):
        from app.core import task_history_signals

        token = backend_lang.bind_request_lang("en")
        try:
            headers = {"id": "abc", "lang": "py"}
            task_history_signals.on_before_task_publish(headers=headers)
            assert headers["lp_lang"] == "en"
            assert headers["lang"] == "py"  # 不覆盖 Celery 自带头
        finally:
            backend_lang.reset_request_lang(token)

    def test_before_task_publish_without_request_does_not_inject(self):
        from app.core import task_history_signals

        headers = {"id": "abc"}
        task_history_signals.on_before_task_publish(headers=headers)
        assert "lp_lang" not in headers
