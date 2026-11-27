"""LP-146：存量 ZV 波阻抗参数定义的启动改名（幂等）。"""

from __future__ import annotations

import os
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("MINIO_ENABLED", "false")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.core.database import Base, rename_zv_impedance_param_definitions
from app.models.atp_param_definition import AtpParamDefinition


def _build_session():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)()


def _add(session, code: str, name: str, description: str) -> None:
    now = datetime.now(timezone.utc)
    session.add(
        AtpParamDefinition(
            id=code,
            code=code,
            name=name,
            unit="Ω",
            data_type="number",
            source_type="line_binding",
            binding_json={},
            deps_json=[],
            enabled=True,
            sort_order=0,
            description=description,
            created_at=now,
            updated_at=now,
        )
    )


def test_rename_zv_impedance_param_definitions_is_idempotent() -> None:
    session = _build_session()
    try:
        _add(session, "tower_z_1", "塔材波阻抗1", "线路管理-塔材波阻抗1，→ ZRE01_")
        _add(session, "tower_z_2", "塔材波阻抗2", "线路管理-塔材波阻抗2，→ ZRE02_")
        _add(session, "tower_z_3", "塔材波阻抗3", "线路管理-塔材波阻抗3，→ ZRE03_")
        # 已被手工改名的行不动
        _add(session, "tower_z_1_custom", "主材波阻抗", "自定义")
        session.commit()

        assert rename_zv_impedance_param_definitions(session) is True
        session.commit()

        rows = {row.code: row for row in session.execute(select(AtpParamDefinition)).scalars()}
        assert rows["tower_z_1"].name == "主材波阻抗"
        assert rows["tower_z_2"].name == "横材波阻抗"
        assert rows["tower_z_3"].name == "斜材波阻抗"
        assert rows["tower_z_1"].description == "线路管理-主材波阻抗，→ ZRE01_"
        assert rows["tower_z_1_custom"].description == "自定义"

        # 第二次执行无旧名可改 → False
        assert rename_zv_impedance_param_definitions(session) is False
    finally:
        session.close()
