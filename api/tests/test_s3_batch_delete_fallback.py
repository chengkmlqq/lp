from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock


def _ensure_boto3() -> None:
    """本地/精简环境未安装 boto3 时注入最小 stub。

    S3StorageDriver.__init__ 只用到 boto3.session.Session(...).client(...) 与
    botocore.config.Config；测试随后会用 MagicMock 覆盖 _client，因此 stub 足够。
    CI 装了 boto3 时不会走到这里。
    """
    try:
        import boto3  # noqa: F401
        import botocore.config  # noqa: F401
        return
    except ModuleNotFoundError:
        pass

    boto3_stub = types.ModuleType("boto3")
    boto3_stub.session = types.SimpleNamespace(
        Session=lambda **kwargs: types.SimpleNamespace(client=lambda *a, **k: MagicMock())
    )
    botocore_stub = types.ModuleType("botocore")
    config_stub = types.ModuleType("botocore.config")
    config_stub.Config = lambda **kwargs: dict(kwargs)
    botocore_stub.config = config_stub
    sys.modules.setdefault("boto3", boto3_stub)
    sys.modules.setdefault("botocore", botocore_stub)
    sys.modules.setdefault("botocore.config", config_stub)


_ensure_boto3()

from app.services.storage_driver import S3StorageDriver, StorageDriverError  # noqa: E402


def _make_driver() -> S3StorageDriver:
    return S3StorageDriver(
        config={
            "bucket": "lp-files",
            "endpoint_url": "https://oss-cn-beijing.aliyuncs.com",
            "region_name": "cn-north-1",
            "access_key_id": "abcdef123456",
            "secret_access_key": "supersecret",
        },
        mount_root_path="/",
    )


class S3BatchDeleteFallbackTest(unittest.TestCase):
    """OSS 的 DeleteMultipleObjects 会拒绝 botocore 的 DeleteObjects 请求
    （MissingArgument），删除必须降级为逐个 delete_object，否则文件管理/模型删除 502。"""

    def test_falls_back_to_single_delete_when_batch_rejected(self) -> None:
        driver = _make_driver()
        driver._client = MagicMock()
        driver._client.delete_objects.side_effect = RuntimeError("Missing Some Required Arguments")

        driver._delete_keys(["atp-assets/a/work.atp", "atp-assets/a/long.dat"])

        self.assertEqual(
            [call.kwargs["Key"] for call in driver._client.delete_object.call_args_list],
            ["atp-assets/a/work.atp", "atp-assets/a/long.dat"],
        )
        # 降级后不再重复尝试失败的批量接口
        self.assertFalse(driver._batch_delete_supported)

    def test_skips_batch_after_first_failure(self) -> None:
        driver = _make_driver()
        driver._client = MagicMock()
        driver._client.delete_objects.side_effect = RuntimeError("Missing Some Required Arguments")

        driver._delete_keys(["a/1.txt"])
        driver._delete_keys(["a/2.txt"])

        self.assertEqual(driver._client.delete_objects.call_count, 1)
        self.assertEqual(driver._client.delete_object.call_count, 2)

    def test_uses_batch_when_supported(self) -> None:
        driver = _make_driver()
        driver._client = MagicMock()

        driver._delete_keys(["a/1.txt", "a/2.txt"])

        driver._client.delete_objects.assert_called_once()
        driver._client.delete_object.assert_not_called()

    def test_raises_storage_error_when_single_delete_fails(self) -> None:
        driver = _make_driver()
        driver._client = MagicMock()
        driver._client.delete_objects.side_effect = RuntimeError("Missing Some Required Arguments")
        driver._client.delete_object.side_effect = RuntimeError("AccessDenied")

        with self.assertRaises(StorageDriverError) as ctx:
            driver._delete_keys(["a/1.txt"])

        self.assertIn("S3 delete failed", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
