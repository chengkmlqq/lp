from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.line import Line
from app.models.line_tower import LineTower
from app.models.lightning_distribution import LightningDistribution
from app.services import lightning_service


def _build_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        bind=engine,
        tables=[Line.__table__, LightningDistribution.__table__, LineTower.__table__],
    )
    testing_session = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    return testing_session()


def _add_line(
    session: Session,
    *,
    line_id: str,
    code: str,
    name: str,
    voltage_kv: int | None = 110,
) -> Line:
    line = Line(
        id=line_id,
        code=code,
        name=name,
        voltage_kv=voltage_kv,
    )
    session.add(line)
    session.flush()
    return line


def _add_tower(
    session: Session,
    *,
    line_id: str,
    tower_no: str,
    seq_no: int,
    distribution_id: str | None = None,
    prepared_at: str | None = None,
) -> LineTower:
    raw_extra_json = {}
    if distribution_id:
        raw_extra_json = {
            "lightning_density": {
                "line_id": line_id,
                "line_code": "DG",
                "radius_km": 3.0,
                "data_years": 5.0,
                "strike_count": 10,
                "region_id": "r1",
                "prepared_at": prepared_at or "2026-08-08T00:00:00+00:00",
                "source_distribution_id": distribution_id,
            }
        }
    tower = LineTower(
        id=f"t-{line_id}-{seq_no}",
        line_id=line_id,
        tower_no=tower_no,
        seq_no=seq_no,
        raw_extra_json=raw_extra_json,
    )
    session.add(tower)
    session.flush()
    return tower


def _add_distribution(session: Session, *, distribution_id: str) -> LightningDistribution:
    dist = LightningDistribution(
        id=distribution_id,
        source_file_name="dist.csv",
    )
    session.add(dist)
    session.flush()
    return dist


def test_linked_lines_aggregates_by_line_id_and_join_line_meta() -> None:
    session = _build_session()
    try:
        _add_line(session, line_id="l1", code="DG-110-1", name="第一条线", voltage_kv=110)
        _add_line(session, line_id="l2", code="DG-500-2", name="第二条线", voltage_kv=500)
        _add_distribution(session, distribution_id="d1")

        # 线路 l1 两条杆塔引用 d1，线路 l2 一条引用 d1
        _add_tower(session, line_id="l1", tower_no="A1", seq_no=1, distribution_id="d1")
        _add_tower(session, line_id="l1", tower_no="A2", seq_no=2, distribution_id="d1")
        _add_tower(session, line_id="l2", tower_no="B1", seq_no=1, distribution_id="d1")
        # 无关杆塔（未回填）不应计入
        _add_tower(session, line_id="l2", tower_no="B2", seq_no=2, distribution_id=None)
        session.commit()

        response = lightning_service.get_linked_lines_for_distribution(session, "d1")

        assert response.total == 2
        by_line = {item.line_id: item for item in response.items}
        assert by_line["l1"].tower_count == 2
        assert by_line["l1"].line_code == "DG-110-1"
        assert by_line["l1"].line_name == "第一条线"
        assert by_line["l1"].voltage_kv == 110
        assert "2026-08-08" in (by_line["l1"].prepared_at or "")
        assert by_line["l2"].tower_count == 1
        assert by_line["l2"].line_code == "DG-500-2"
        assert by_line["l2"].voltage_kv == 500
    finally:
        session.close()


def test_linked_lines_returns_distinct_towers_vs_distinct_lines() -> None:
    """tower_count 统计杆塔数，total 统计线路数（去重）。"""
    session = _build_session()
    try:
        _add_line(session, line_id="l1", code="L1", name="线1")
        _add_distribution(session, distribution_id="d2")
        _add_tower(session, line_id="l1", tower_no="T1", seq_no=1, distribution_id="d2")
        _add_tower(session, line_id="l1", tower_no="T2", seq_no=2, distribution_id="d2")
        session.commit()

        response = lightning_service.get_linked_lines_for_distribution(session, "d2")
        assert response.total == 1
        assert response.items[0].line_id == "l1"
        assert response.items[0].tower_count == 2
    finally:
        session.close()


def test_linked_lines_empty_when_no_reference() -> None:
    session = _build_session()
    try:
        _add_line(session, line_id="l1", code="L1", name="线1")
        _add_distribution(session, distribution_id="d3")
        _add_tower(session, line_id="l1", tower_no="T1", seq_no=1, distribution_id=None)
        session.commit()

        response = lightning_service.get_linked_lines_for_distribution(session, "d3")
        assert response.total == 0
        assert response.items == []
    finally:
        session.close()


def test_linked_lines_missing_distribution_raises_404() -> None:
    session = _build_session()
    try:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as captured:
            lightning_service.get_linked_lines_for_distribution(session, "does-not-exist")
        assert captured.value.status_code == 404
    finally:
        session.close()


def test_distribution_linked_line_count() -> None:
    session = _build_session()
    try:
        _add_line(session, line_id="l1", code="L1", name="线1")
        _add_line(session, line_id="l2", code="L2", name="线2")
        _add_distribution(session, distribution_id="d4")
        _add_tower(session, line_id="l1", tower_no="A1", seq_no=1, distribution_id="d4")
        _add_tower(session, line_id="l1", tower_no="A2", seq_no=2, distribution_id="d4")
        _add_tower(session, line_id="l2", tower_no="B1", seq_no=1, distribution_id="d4")
        session.commit()

        assert lightning_service.get_distribution_linked_line_count(session, "d4") == 2
    finally:
        session.close()


def test_list_lightning_distributions_injects_linked_line_count() -> None:
    session = _build_session()
    try:
        _add_line(session, line_id="l1", code="L1", name="线1")
        _add_line(session, line_id="l2", code="L2", name="线2")
        _add_distribution(session, distribution_id="dA")
        _add_distribution(session, distribution_id="dB")
        _add_tower(session, line_id="l1", tower_no="A1", seq_no=1, distribution_id="dA")
        _add_tower(session, line_id="l2", tower_no="B1", seq_no=1, distribution_id="dB")
        _add_tower(session, line_id="l2", tower_no="B2", seq_no=2, distribution_id="dB")
        session.commit()

        result = lightning_service.list_lightning_distributions(session, keyword=None, limit=50, offset=0)
        by_id = {item.id: item for item in result.items}
        assert by_id["dA"].linked_line_count == 1
        assert by_id["dB"].linked_line_count == 1
    finally:
        session.close()


def test_list_lightning_distributions_linked_count_null_safe() -> None:
    """无任何回填时 linked_line_count 应为 0（前端可降级展示 0）。"""
    session = _build_session()
    try:
        _add_distribution(session, distribution_id="dEmpty")
        session.commit()

        result = lightning_service.list_lightning_distributions(session, keyword=None, limit=50, offset=0)
        assert result.items[0].linked_line_count == 0
    finally:
        session.close()
