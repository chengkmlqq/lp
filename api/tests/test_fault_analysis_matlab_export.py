from __future__ import annotations

"""LP-402: 故障分析详情页导出改为直接交付 MATLAB Runtime 引擎产物。

覆盖后端导出引擎产物接口 ``GET /{id}/export-matlab`` 的行为：
- 按 artifacts.matlab_outputs 清单拉取（单文件直传 / 多文件 zip 打包）
- 清单为空时按 Output/matlab/ 前缀兜底列举
- 仍为空时返回 404 明确提示「该次分析未运行引擎」
"""

import io
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1 import fault_analysis as fault_analysis_api
from app.services.minio_storage import FAULT_ANALYSIS_PREFIX


def _analysis(analysis_id: str, keys: list[str]) -> SimpleNamespace:
    item = SimpleNamespace()
    item.id = analysis_id
    item.result_json = {"artifacts": {"matlab_outputs": keys}}
    return item


def _empty_analysis(analysis_id: str) -> SimpleNamespace:
    item = SimpleNamespace()
    item.id = analysis_id
    item.result_json = {"artifacts": {}}
    return item


def _patch_store(monkeypatch, stored: dict[str, bytes]) -> None:
    """把 API 层引用的 minio 函数替换为以 store dict 作为后端的 mock。"""

    def fake_get_object(key: str) -> bytes:
        if key not in stored:
            from app.services.minio_storage import MinioObjectNotFoundError

            raise MinioObjectNotFoundError(f"Object not found: {key}")
        return stored[key]

    def fake_list_objects(prefix: str) -> list[str]:
        return [key for key in stored if key.startswith(prefix)]

    monkeypatch.setattr(fault_analysis_api, "get_object", fake_get_object)
    monkeypatch.setattr(fault_analysis_api, "list_objects", fake_list_objects)


def _response_body(response) -> bytes:
    """读取 StreamingResponse 的响应体（兼容新版 Starlette 的 async body_iterator）。"""
    import asyncio

    iterator = response.body_iterator
    chunks: list[bytes] = []

    async def _collect_async() -> None:
        async for chunk in iterator:
            chunks.append(chunk)

    if hasattr(iterator, "__aiter__"):
        asyncio.run(_collect_async())
    else:
        chunks.extend(iterator)
    return b"".join(chunks)


def _call_endpoint(analysis_id: str):
    """直接调用导出端点（跳过 FastAPI 依赖注入层）。"""
    return fault_analysis_api.export_fault_analysis_matlab_outputs(
        analysis_id, _=None, db=SimpleNamespace()
    )


def test_export_matlab_single_file_streamed(monkeypatch):
    analysis_id = "fa-single"
    key = f"{FAULT_ANALYSIS_PREFIX}{analysis_id}/Output/matlab/20260817/prediction.txt"
    monkeypatch.setattr(
        fault_analysis_api,
        "get_analysis_by_id",
        lambda _db, _id: _analysis(analysis_id, [key]) if _id == analysis_id else None,
    )
    _patch_store(monkeypatch, {key: "mechanism=雷击\n".encode("utf-8")})

    response = _call_endpoint(analysis_id)

    assert _response_body(response) == "mechanism=雷击\n".encode("utf-8")
    disposition = response.headers.get("Content-Disposition", "")
    assert "prediction.txt" in disposition
    assert "filename*=UTF-8''" in disposition


def test_export_matlab_multiple_files_packaged_as_zip(monkeypatch):
    analysis_id = "fa-multi"
    prefix = f"{FAULT_ANALYSIS_PREFIX}{analysis_id}/Output/matlab/"
    keys = [
        f"{prefix}20260817/classification_result.mat",
        f"{prefix}20260817/行波分析结果.txt",
        f"{prefix}20260817/sub/分类汇总.xlsx",
    ]
    monkeypatch.setattr(
        fault_analysis_api,
        "get_analysis_by_id",
        lambda _db, _id: _analysis(analysis_id, keys) if _id == analysis_id else None,
    )
    stored = {key: f"content-{i}-data".encode() for i, key in enumerate(keys)}
    _patch_store(monkeypatch, stored)

    response = _call_endpoint(analysis_id)

    assert response.headers.get("Content-Type") == "application/zip"
    disposition = response.headers.get("Content-Disposition", "")
    assert f"fault_analysis_{analysis_id}_matlab_outputs.zip" in disposition
    archive = zipfile.ZipFile(io.BytesIO(_response_body(response)))
    names = archive.namelist()
    # zip 内保留 Output/matlab/<run_id>/ 的相对路径
    assert any(name.endswith("classification_result.mat") for name in names)
    assert any(name.endswith("行波分析结果.txt") for name in names)
    assert any(name.endswith("sub/分类汇总.xlsx") for name in names)
    assert archive.read([n for n in names if n.endswith("classification_result.mat")][0]) == b"content-0-data"


def test_export_matlab_falls_back_to_prefix_list(monkeypatch):
    """artifacts.matlab_outputs 缺失/为空时，按 Output/matlab/ 前缀列举兜底。"""
    analysis_id = "fa-fallback"
    prefix = f"{FAULT_ANALYSIS_PREFIX}{analysis_id}/Output/matlab/"
    fallback_key = f"{prefix}20260817/wave_module_prediction.txt"
    monkeypatch.setattr(
        fault_analysis_api,
        "get_analysis_by_id",
        lambda _db, _id: _empty_analysis(analysis_id) if _id == analysis_id else None,
    )
    monkeypatch.setattr(fault_analysis_api, "get_object", lambda key: b"prediction-content")
    monkeypatch.setattr(fault_analysis_api, "list_objects", lambda prefix_arg: [fallback_key])

    response = _call_endpoint(analysis_id)

    assert _response_body(response) == b"prediction-content"
    assert "prediction.txt" in response.headers.get("Content-Disposition", "")


def test_export_matlab_no_outputs_raises_404(monkeypatch):
    analysis_id = "fa-empty"
    monkeypatch.setattr(
        fault_analysis_api,
        "get_analysis_by_id",
        lambda _db, _id: _empty_analysis(analysis_id) if _id == analysis_id else None,
    )
    monkeypatch.setattr(fault_analysis_api, "list_objects", lambda _prefix: [])
    monkeypatch.setattr(fault_analysis_api, "_matlab_output_vfs_files", lambda _id: [])

    with pytest.raises(HTTPException) as exc_info:
        _call_endpoint(analysis_id)
    assert exc_info.value.status_code == 404
    assert "未运行引擎" in str(exc_info.value.detail)


def test_export_matlab_missing_record_raises_404(monkeypatch):
    monkeypatch.setattr(fault_analysis_api, "get_analysis_by_id", lambda _db, _id: None)

    with pytest.raises(HTTPException) as exc_info:
        _call_endpoint("fa-missing")
    assert exc_info.value.status_code == 404


def test_list_objects_paginates_all_keys(monkeypatch):
    """list_objects 应跨分页拼接全部匹配 key。"""
    from app.services import minio_storage

    pages = [["a/1.txt", "a/2.txt"], [], ["a/3.txt"]]
    index = {"n": 0}

    class _FakeClient:
        def get_paginator(self, name):
            assert name == "list_objects_v2"

            def paginate(**kwargs):
                for page in pages:
                    yield {"Contents": [{"Key": k} for k in page]}

            return SimpleNamespace(paginate=paginate)

    monkeypatch.setattr(minio_storage, "_build_client", lambda: _FakeClient())
    monkeypatch.setattr(
        minio_storage,
        "get_settings",
        lambda: SimpleNamespace(minio_bucket="bkt", minio_enabled=True),
    )

    assert minio_storage.list_objects("a/") == ["a/1.txt", "a/2.txt", "a/3.txt"]
