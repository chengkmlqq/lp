from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from api.app.models.file_storage import FileStorageBackend
from api.app.services.seed_service import _reconcile_s3_default_config
from api.app.services.storage_driver import S3StorageDriver, StorageDriverError


def _make_driver() -> S3StorageDriver:
    return S3StorageDriver(
        config={
            "bucket": "lp-files",
            "endpoint_url": "http://minio:9000",
            "region_name": "us-east-1",
            "access_key_id": "abcdef123456",
            "secret_access_key": "supersecret",
        },
        mount_root_path="/",
    )


class S3WriteFailureDiagnosticsTest(unittest.TestCase):
    """LP-205: S3 SignatureDoesNotMatch must surface diagnosable info, no secret leak."""

    def test_write_file_error_includes_bucket_endpoint_region_and_redacted_key(self) -> None:
        driver = _make_driver()
        driver._client = MagicMock()
        driver._client.put_object.side_effect = RuntimeError("SignatureDoesNotMatch")

        with self.assertRaises(StorageDriverError) as ctx:
            driver.write_file("/elevation/records/x.tif", content=b"data")

        message = str(ctx.exception)
        self.assertIn("S3 upload failed", message)
        self.assertIn("bucket='lp-files'", message)
        self.assertIn("http://minio:9000", message)
        self.assertIn("us-east-1", message)
        # Redacted access key id prefix (not the full value).
        self.assertIn("****abcd", message)
        self.assertNotIn("abcdef123456", message)
        # Never leak the secret access key.
        self.assertNotIn("supersecret", message)

    def test_write_file_error_omits_key_fields_when_absent(self) -> None:
        driver = S3StorageDriver(
            config={"bucket": "b"},
            mount_root_path="/",
        )
        driver._client = MagicMock()
        driver._client.put_object.side_effect = RuntimeError("boom")

        with self.assertRaises(StorageDriverError) as ctx:
            driver.write_file("/a.tif", content=b"x")

        message = str(ctx.exception)
        self.assertIn("S3 upload failed", message)
        self.assertNotIn("access_key_id_prefix", message)


class S3DefaultConfigReconcileTest(unittest.TestCase):
    """LP-205: seed must refresh S3 default backend config from env when it drifts."""

    def _backend(self, config: dict) -> FileStorageBackend:
        return FileStorageBackend(
            id=1,
            code="files.s3.default",
            name="S3 对象存储",
            driver_type="S3",
            status="enabled",
            is_default=True,
            config_json=dict(config),
        )

    def test_reconcile_updates_drifted_fields_and_reports_change(self) -> None:
        backend = self._backend(
            {
                "bucket": "old-bucket",
                "region_name": "us-east-1",
                "endpoint_url": "http://minio:9000",
                "access_key_id": "old_access",
                "secret_access_key": "old_secret",
            }
        )
        desired = {
            "bucket": "lp-files",
            "region_name": "us-east-1",
            "endpoint_url": "http://minio:9000",
            "access_key_id": "new_access",
            "secret_access_key": "new_secret",
        }
        changed = _reconcile_s3_default_config(backend, desired)
        self.assertTrue(changed)
        self.assertEqual(backend.config_json["bucket"], "lp-files")
        self.assertEqual(backend.config_json["access_key_id"], "new_access")
        self.assertEqual(backend.config_json["secret_access_key"], "new_secret")

    def test_reconcile_no_change_when_in_sync(self) -> None:
        desired = {
            "bucket": "lp-files",
            "region_name": "us-east-1",
            "endpoint_url": "http://minio:9000",
            "access_key_id": "a",
            "secret_access_key": "s",
        }
        backend = self._backend(dict(desired))
        changed = _reconcile_s3_default_config(backend, desired)
        self.assertFalse(changed)

    def test_reconcile_preserves_non_managed_keys(self) -> None:
        backend = self._backend(
            {
                "bucket": "old",
                "user_key": "keep-me",
                "region_name": "us-east-1",
                "endpoint_url": "http://minio:9000",
                "access_key_id": "a",
                "secret_access_key": "s",
            }
        )
        self.assertTrue(
            _reconcile_s3_default_config(
                backend,
                {
                    "bucket": "new-bucket",
                    "region_name": "us-east-1",
                    "endpoint_url": "http://minio:9000",
                    "access_key_id": "a",
                    "secret_access_key": "s",
                },
            )
        )
        # Bucket reconciled...
        self.assertEqual(backend.config_json["bucket"], "new-bucket")
        # ...but unrelated user keys are untouched.
        self.assertEqual(backend.config_json["user_key"], "keep-me")


if __name__ == "__main__":
    unittest.main()