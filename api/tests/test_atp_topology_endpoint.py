from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
import pytest
from sqlalchemy.orm import Session

from app.models.atp_asset import AtpAsset, AtpAssetRelease
from app.services.atp_asset_service import get_asset_topology

from test_atp_asset_service import _build_sessionmaker, _seed_vfs_mount

REPO_ROOT = Path(__file__).resolve().parents[2]
FANJI_TEMPLATE = REPO_ROOT / "deploy" / "dev-deploy" / "data" / "app" / "wine" / "ATP" / "templates" / "fanji" / "work.atp"


def _seed_asset_with_release(session: Session, *, code: str, entry_file: str = "work.atp") -> AtpAsset:
    asset = AtpAsset(
        code=code,
        name=f"资产 {code}",
        description="",
        status="enabled",
        voltage_level="110",
        tower_type="ganzi",
        scene_type="fanji",
        arrester_config="M1",
        storage_mount_code="main",
        storage_root_path=f"/atp-assets/{code}",
        latest_release_no=0,
    )
    session.add(asset)
    session.flush()
    release = AtpAssetRelease(
        asset_id=asset.id,
        release_no=1,
        status="released",
        voltage_level="110",
        tower_type="ganzi",
        scene_type="fanji",
        storage_mount_code="main",
        storage_root_path=f"/atp-assets/{code}",
        entry_file=entry_file,
        content_hash="x",
        is_active=True,
    )
    session.add(release)
    session.flush()
    return asset


def test_get_asset_topology_with_active_release_returns_topology(tmp_path) -> None:
    """有 active release 时，返回 200 语义 + 合法拓扑 JSON。"""
    session: Session = _build_sessionmaker()()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset_dir = tmp_path / "vfs" / "atp-assets" / "atp-topo-ok"
        asset_dir.mkdir(parents=True)
        asset_dir.joinpath("work.atp").write_bytes(FANJI_TEMPLATE.read_bytes())
        session.flush()

        asset = _seed_asset_with_release(session, code="atp-topo-ok")
        resp = get_asset_topology(session, asset_id=asset.id)

        assert resp.asset_id == asset.id
        assert resp.release_id is not None
        assert len(resp.topology.nodes) >= 7
        assert len(resp.topology.edges) >= 8
        assert resp.topology.parameters["RER001"] == pytest.approx(15.0)
        # 主链路拓扑
        edge_pairs = {(edge.source, edge.target) for edge in resp.topology.edges}
        assert ("gnd", "rg") in edge_pairs
        assert ("rg", "tower") in edge_pairs
        assert ("tower", "ins") in edge_pairs
        assert ("ins", "source") in edge_pairs
    finally:
        session.close()


def test_get_asset_topology_falls_back_to_first_release(tmp_path) -> None:
    """无 active release 时回退到第一个 release。"""
    session: Session = _build_sessionmaker()()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset_dir = tmp_path / "vfs" / "atp-assets" / "atp-topo-fallback"
        asset_dir.mkdir(parents=True)
        asset_dir.joinpath("work.atp").write_bytes(FANJI_TEMPLATE.read_bytes())
        session.flush()

        asset = AtpAsset(
            code="atp-topo-fallback",
            name="回退资产",
            description="",
            status="enabled",
            storage_mount_code="main",
            storage_root_path="/atp-assets/atp-topo-fallback",
            latest_release_no=1,
        )
        session.add(asset)
        session.flush()
        session.add(
            AtpAssetRelease(
                asset_id=asset.id,
                release_no=1,
                status="released",
                voltage_level="110",
                tower_type="ganzi",
                scene_type="fanji",
                storage_mount_code="main",
                storage_root_path="/atp-assets/atp-topo-fallback",
                entry_file="work.atp",
                content_hash="x",
                is_active=False,
            )
        )
        session.flush()

        resp = get_asset_topology(session, asset_id=asset.id)
        assert len(resp.topology.nodes) >= 7
        assert resp.release_id is not None
    finally:
        session.close()


def test_get_asset_topology_no_release_returns_404(tmp_path) -> None:
    """无 release 时返回 404。"""
    session: Session = _build_sessionmaker()()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = AtpAsset(
            code="atp-topo-no-release",
            name="无版本",
            description="",
            status="enabled",
            storage_mount_code="main",
            storage_root_path="/atp-assets/atp-topo-no-release",
            latest_release_no=0,
        )
        session.add(asset)
        session.flush()

        with pytest.raises(HTTPException) as exc_info:
            get_asset_topology(session, asset_id=asset.id)
        assert exc_info.value.status_code == 404
    finally:
        session.close()


def test_get_asset_topology_missing_file_returns_404(tmp_path) -> None:
    """文件缺失时返回 404。"""
    session: Session = _build_sessionmaker()()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset_dir = tmp_path / "vfs" / "atp-assets" / "atp-topo-missing"
        asset_dir.mkdir(parents=True)
        session.flush()

        asset = _seed_asset_with_release(session, code="atp-topo-missing")
        with pytest.raises(HTTPException) as exc_info:
            get_asset_topology(session, asset_id=asset.id)
        assert exc_info.value.status_code == 404
    finally:
        session.close()


def test_get_asset_topology_unknown_asset_returns_404(tmp_path) -> None:
    """资产不存在时返回 404。"""
    session: Session = _build_sessionmaker()()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        with pytest.raises(HTTPException) as exc_info:
            get_asset_topology(session, asset_id="does-not-exist")
        assert exc_info.value.status_code == 404
    finally:
        session.close()
