from __future__ import annotations

from datetime import datetime, timezone

from ..core.config import get_settings


class TaskLogServiceError(RuntimeError):
    pass


class TaskLogNotFoundError(TaskLogServiceError):
    pass


def _get_log_path(task_id: str, timestamp: datetime | None = None) -> str:
    """
    Generate log path in MinIO following the pattern: logs/YYYY/MM/DD/{task_id}.log
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)

    year = timestamp.strftime("%Y")
    month = timestamp.strftime("%m")
    day = timestamp.strftime("%d")

    return f"logs/{year}/{month}/{day}/{task_id}.log"


def upload_task_log(task_id: str, log_content: str) -> tuple[str, datetime]:
    """
    Upload task execution log to MinIO.
    Returns: (log_path, uploaded_at)
    """
    settings = get_settings()

    if not settings.minio_enabled:
        raise TaskLogServiceError("MinIO storage is not enabled")

    try:
        import boto3
        from botocore.config import Config
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError as exc:
        raise TaskLogServiceError("boto3 library is required for MinIO storage") from exc

    uploaded_at = datetime.now(timezone.utc)
    log_path = _get_log_path(task_id, uploaded_at)

    try:
        client_config = Config(
            connect_timeout=3.0,
            read_timeout=10.0,
            retries={"max_attempts": 2},
        )

        session = boto3.session.Session(
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
        )

        client = session.client(
            "s3",
            endpoint_url=settings.minio_endpoint,
            region_name=settings.minio_region,
            config=client_config,
        )

        # Upload log content as text file
        client.put_object(
            Bucket=settings.minio_bucket,
            Key=log_path,
            Body=log_content.encode("utf-8"),
            ContentType="text/plain; charset=utf-8",
        )

        return log_path, uploaded_at

    except (BotoCoreError, ClientError) as exc:
        raise TaskLogServiceError(f"Failed to upload log to MinIO: {exc}") from exc
    except Exception as exc:
        raise TaskLogServiceError(f"Unexpected error during log upload: {exc}") from exc


def get_task_log(task_id: str, log_date: datetime | None = None) -> tuple[str, str]:
    """
    Retrieve task execution log from MinIO.
    If log_date is not provided, tries to find the log for today.
    Returns: (log_content, log_path)
    """
    settings = get_settings()

    if not settings.minio_enabled:
        raise TaskLogServiceError("MinIO storage is not enabled")

    try:
        import boto3
        from botocore.config import Config
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError as exc:
        raise TaskLogServiceError("boto3 library is required for MinIO storage") from exc

    if log_date is None:
        log_date = datetime.now(timezone.utc)

    log_path = _get_log_path(task_id, log_date)

    try:
        client_config = Config(
            connect_timeout=3.0,
            read_timeout=10.0,
            retries={"max_attempts": 2},
        )

        session = boto3.session.Session(
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
        )

        client = session.client(
            "s3",
            endpoint_url=settings.minio_endpoint,
            region_name=settings.minio_region,
            config=client_config,
        )

        response = client.get_object(
            Bucket=settings.minio_bucket,
            Key=log_path,
        )

        body = response.get("Body")
        if body is None:
            raise TaskLogServiceError("Log file body is empty")

        log_content = body.read().decode("utf-8")
        return log_content, log_path

    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code in {"404", "NoSuchKey", "NotFound"}:
            raise TaskLogNotFoundError(f"Log not found for task {task_id} at path {log_path}") from exc
        raise TaskLogServiceError(f"Failed to retrieve log from MinIO: {exc}") from exc
    except (BotoCoreError, UnicodeDecodeError) as exc:
        raise TaskLogServiceError(f"Failed to read log content: {exc}") from exc
    except Exception as exc:
        raise TaskLogServiceError(f"Unexpected error during log retrieval: {exc}") from exc


def list_task_logs(task_id: str) -> list[str]:
    """
    List all available logs for a task across all dates.
    Returns: list of log paths
    """
    settings = get_settings()

    if not settings.minio_enabled:
        raise TaskLogServiceError("MinIO storage is not enabled")

    try:
        import boto3
        from botocore.config import Config
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError as exc:
        raise TaskLogServiceError("boto3 library is required for MinIO storage") from exc

    try:
        client_config = Config(
            connect_timeout=3.0,
            read_timeout=10.0,
            retries={"max_attempts": 2},
        )

        session = boto3.session.Session(
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
        )

        client = session.client(
            "s3",
            endpoint_url=settings.minio_endpoint,
            region_name=settings.minio_region,
            config=client_config,
        )

        # Search for all logs matching the task_id pattern
        prefix = "logs/"
        suffix = f"/{task_id}.log"

        log_paths: list[str] = []
        paginator = client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=settings.minio_bucket, Prefix=prefix)

        for page in pages:
            for item in page.get("Contents", []):
                key = item.get("Key", "")
                if key.endswith(suffix):
                    log_paths.append(key)

        return sorted(log_paths, reverse=True)  # Most recent first

    except (BotoCoreError, ClientError) as exc:
        raise TaskLogServiceError(f"Failed to list logs from MinIO: {exc}") from exc
    except Exception as exc:
        raise TaskLogServiceError(f"Unexpected error during log listing: {exc}") from exc
