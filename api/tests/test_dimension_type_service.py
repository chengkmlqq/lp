from __future__ import annotations

import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.core.database import Base
from app.models.dimension_item import DimensionItem
from app.models.dimension_type import DimensionType
from app.models.user import User
from app.schemas.dimension_type import (
    DimensionTypeCreateRequest,
    DimensionTypeUpdateRequest,
)
from app.services.dimension_type_service import (
    create_dimension_type,
    delete_dimension_type,
    get_dimension_type_tree,
    update_dimension_type,
)


class DimensionTypeServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(
            bind=self.engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
        Base.metadata.create_all(bind=self.engine)
        self.session = self.SessionLocal()
        self.actor = User(id="u-test", username="tester", password_hash="x")
        self.session.add(self.actor)
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _create_type(self, code: str = "voltage_level", name: str = "电压等级", **overrides) -> DimensionType:
        req = DimensionTypeCreateRequest(
            code=code,
            name=name,
            sort_order=overrides.get("sort_order", 0),
            parent_id=overrides.get("parent_id"),
        )
        created = create_dimension_type(self.session, req, actor=self.actor)
        assert created is not None
        row = self.session.scalar(select(DimensionType).where(DimensionType.id == created.id))
        assert row is not None
        return row

    def test_create_and_tree(self) -> None:
        parent = self._create_type(code="parent_type", name="父类型")
        child = self._create_type(code="child_type", name="子类型", parent_id=parent.id)
        self.assertEqual(parent.parent_id, None)
        self.assertEqual(child.parent_id, parent.id)

        tree = get_dimension_type_tree(self.session)
        self.assertEqual(len(tree), 1)
        self.assertEqual(tree[0].code, "parent_type")
        self.assertEqual(len(tree[0].children), 1)
        self.assertEqual(tree[0].children[0].code, "child_type")

    def test_code_duplicate_returns_none(self) -> None:
        self._create_type(code="voltage_level")
        duplicate = create_dimension_type(
            self.session,
            DimensionTypeCreateRequest(code="voltage_level", name="重复类型"),
            actor=self.actor,
        )
        self.assertIsNone(duplicate)

    def test_update_type(self) -> None:
        row = self._create_type(name="电压等级")
        updated = update_dimension_type(
            self.session,
            row.id,
            DimensionTypeUpdateRequest(name="电压等级（更新）", is_enabled=False),
            actor=self.actor,
        )
        assert updated is not None
        self.assertEqual(updated.name, "电压等级（更新）")
        self.assertFalse(updated.is_enabled)

    def test_delete_type_related_referenced_returns_false(self) -> None:
        row = self._create_type()
        self.session.add(
            DimensionItem(
                dimension_type="voltage_level",
                type_id=row.id,
                code="110kv",
                name="110千伏",
            )
        )
        self.session.commit()
        # 有维度值引用 -> 拒绝删除（409）
        self.assertFalse(delete_dimension_type(self.session, row.id))
        self.session.expire_all()
        self.assertIsNotNone(
            self.session.scalar(select(DimensionType).where(DimensionType.id == row.id))
        )

    def test_delete_type_unreferenced(self) -> None:
        row = self._create_type()
        self.assertTrue(delete_dimension_type(self.session, row.id))
        tree = get_dimension_type_tree(self.session)
        self.assertEqual(len(tree), 0)


if __name__ == "__main__":
    unittest.main()