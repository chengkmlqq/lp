"""LP-34 后端语言解析单测：APP_LANGUAGE 配置 / 别名归一化 / 任务级优先 / 存量参数清理。"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.core.config import Settings
from app.services import backend_lang


@pytest.fixture
def app_language(monkeypatch):
    """把 ``APP_LANGUAGE``（Settings 读取结果）打桩到指定值。"""

    def _set(value: str) -> None:
        monkeypatch.setattr(
            backend_lang,
            "get_settings",
            lambda: SimpleNamespace(app_language=value),
        )

    return _set


class TestSettingsAppLanguage:
    def test_explicit_en(self):
        assert Settings(_env_file=None, app_language="en").app_language == "en"

    def test_unset_defaults_to_zh(self):
        assert Settings(_env_file=None).app_language == "zh"

    def test_aliases_are_normalized(self):
        assert Settings(_env_file=None, app_language="zh-CN").app_language == "zh"
        assert Settings(_env_file=None, app_language="cn").app_language == "zh"
        assert Settings(_env_file=None, app_language="chinese").app_language == "zh"
        assert Settings(_env_file=None, app_language="en-US").app_language == "en"
        assert Settings(_env_file=None, app_language="english").app_language == "en"

    def test_invalid_value_falls_back_to_zh_with_warning(self, caplog):
        with caplog.at_level(logging.WARNING):
            settings = Settings(_env_file=None, app_language="fr")
        assert settings.app_language == "zh"
        assert "APP_LANGUAGE" in caplog.text

    def test_env_var_is_picked_up(self, monkeypatch):
        monkeypatch.setenv("APP_LANGUAGE", "en")
        assert Settings(_env_file=None).app_language == "en"


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


class TestDefaultLang:
    def test_en_config(self, app_language):
        app_language("en")
        assert backend_lang.get_default_lang() == "en"

    def test_zh_config(self, app_language):
        app_language("zh")
        assert backend_lang.get_default_lang() == "zh"

    def test_never_reads_db(self, app_language):
        """配置驱动：解析默认语言不应触碰数据库。"""
        app_language("en")
        with patch("app.core.database.SessionLocal", side_effect=AssertionError("db accessed")):
            assert backend_lang.get_default_lang() == "en"


class TestResolveBackendLang:
    def test_task_lang_takes_priority(self, app_language):
        app_language("zh")
        assert backend_lang.resolve_backend_lang("en") == "en"

    def test_invalid_task_lang_falls_back_to_config(self, app_language):
        app_language("en")
        assert backend_lang.resolve_backend_lang("fr") == "en"
        assert backend_lang.resolve_backend_lang(None) == "en"

    def test_no_task_lang_uses_config(self, app_language):
        app_language("zh")
        assert backend_lang.resolve_backend_lang() == "zh"


class TestRequestLangContext:
    def test_bind_and_reset(self, app_language):
        app_language("zh")
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


def _sqlite_session_factory():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.core.database import Base

    engine = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)


class TestPurgeLegacyAppLanguageParam:
    def test_removes_existing_row(self):
        from sqlalchemy import select

        from app.core.database import Base, purge_legacy_app_language_param
        from app.models.system_param import SystemParam

        engine, Session = _sqlite_session_factory()
        try:
            with Session() as db:
                db.add(
                    SystemParam(
                        param_key="app.language",
                        param_name="系统语言",
                        param_value="en",
                        is_encrypted=False,
                        status="enabled",
                    )
                )
                db.add(
                    SystemParam(
                        param_key="app.other",
                        param_name="其它参数",
                        param_value="1",
                        is_encrypted=False,
                        status="enabled",
                    )
                )
                db.commit()

            with Session() as db:
                assert purge_legacy_app_language_param(db) is True
                db.commit()

            with Session() as db:
                keys = {row.param_key for row in db.execute(select(SystemParam)).scalars()}
                assert "app.language" not in keys
                assert "app.other" in keys
        finally:
            Base.metadata.drop_all(bind=engine)
            engine.dispose()

    def test_no_row_is_a_noop(self):
        from app.core.database import Base, purge_legacy_app_language_param

        engine, Session = _sqlite_session_factory()
        try:
            with Session() as db:
                assert purge_legacy_app_language_param(db) is False
        finally:
            Base.metadata.drop_all(bind=engine)
            engine.dispose()


class TestBootstrapEndpoint:
    def test_public_endpoint_returns_configured_lang(self, monkeypatch):
        from app.api.v1 import system as system_api

        monkeypatch.setattr(system_api, "get_settings", lambda: SimpleNamespace(app_language="en"))
        assert system_api.get_bootstrap().default_lang == "en"


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
