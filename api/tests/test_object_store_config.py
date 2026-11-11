"""业务对象存储连接配置的解析优先级（OBJECT_STORE_* 优先，回退遗留 MINIO_*）。"""

from types import SimpleNamespace

from app.services import minio_storage


def _patch(monkeypatch, **kwargs):
    monkeypatch.setattr(minio_storage, "get_settings", lambda: SimpleNamespace(**kwargs))


def test_object_store_fields_win(monkeypatch):
    _patch(
        monkeypatch,
        object_store_enabled=True,
        object_store_endpoint="http://minio:9000",
        object_store_access_key="lpminio",
        object_store_secret_key="secret",
        object_store_bucket="lp-files",
        object_store_region="us-east-1",
        object_store_addressing_style="path",
        minio_endpoint="https://oss-cn-beijing.aliyuncs.com",
        minio_access_key="oss-key",
        minio_secret_key="oss-secret",
        minio_bucket="line-protection",
        minio_region="cn-beijing",
    )

    conf = minio_storage.store_conf()

    assert conf["endpoint"] == "http://minio:9000"
    assert conf["bucket"] == "lp-files"
    assert conf["access_key"] == "lpminio"
    assert conf["addressing_style"] == "path"
    assert minio_storage.store_bucket() == "lp-files"


def test_falls_back_to_legacy_minio_when_object_store_empty(monkeypatch):
    _patch(
        monkeypatch,
        object_store_endpoint="",
        object_store_access_key="",
        object_store_secret_key="",
        object_store_bucket="",
        object_store_region="",
        minio_endpoint="https://oss-cn-beijing.aliyuncs.com",
        minio_access_key="oss-key",
        minio_secret_key="oss-secret",
        minio_bucket="line-protection",
        minio_region="cn-beijing",
    )

    conf = minio_storage.store_conf()

    assert conf["endpoint"] == "https://oss-cn-beijing.aliyuncs.com"
    assert conf["bucket"] == "line-protection"
    assert conf["region"] == "cn-beijing"
    # 未声明 addressing_style 时保持历史 OSS 行为（virtual）
    assert conf["addressing_style"] == "virtual"


def test_storage_identity_uses_object_store_endpoint(monkeypatch):
    _patch(
        monkeypatch,
        object_store_endpoint="http://minio:9000/",
        object_store_bucket="lp-files",
        minio_endpoint="https://oss-cn-beijing.aliyuncs.com",
        minio_bucket="line-protection",
    )
    monkeypatch.setattr(minio_storage, "_use_local_backend", lambda: False)

    assert minio_storage.storage_identity() == ("http://minio:9000", "lp-files")
