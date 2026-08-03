from __future__ import annotations

import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.app import models  # noqa: F401
from api.app.core.database import Base
from api.app.models.dimension_item import DimensionItem
from api.app.models.dimension_type import DimensionType
from api.app.models.user import User
from api.app.schemas.dimension_item import (
    DimensionItemCreateRequest,
    DimensionItemUpdateRequest,
)
from api.app.services.dimension_item_service import (
    create_dimension_item,
    get_dimension_tree,
    list_dimension_items,
    update_dimension_item,
)


class DimensionItemTypeFilterTest(unittest.TestCase):
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

        self.vtype = DimensionType(code="voltage_level", name="电压等级")
        self.ttype = DimensionType(code="tower_type", name="塔型")
        self.session.add_all([self.vtype, self.ttype])
        self.session.commit()
        self.session.refresh(self.vtype)
        self.session.refresh(self.ttype)

    def tearDown(self) -> None:
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _add_item(self, type_id: str, code: str, name: str) -> None:
        created = create_dimension_item(
            self.session,
            DimensionItemCreateRequest(
                type_id=type_id,
                
                code=code,
                name=name,
            ),
            actor=self.actor,
        )
        assert created is not None

    def test_create_requires_type_id_and_sets_type_name(self) -> None:
        result = create_dimension_item(
            self.session,
            DimensionItemCreateRequest(type_id=self.vtype.id,  code="110kv", name="110千伏"),
            actor=self.actor,
        )
        assert result is not None
        self.assertEqual(result.type_id, self.vtype.id)
        self.assertEqual(result.type_name, "电压等级")
        # dimension_type 兜底为类型 code
        self.assertEqual(result.dimension_type, "voltage_level")

    def test_type_id_filter(self) -> None:
        self._add_item(self.vtype.id, "110kv", "110千伏")
        self._add_item(self.vtype.id, "220kv", "220千伏")
        self._add_item(self.ttype.id, "cat", "猫头塔")

        page = list_dimension_items(
            self.session,
            limit=50,
            offset=0,
            keyword=None,
            dimension_type=None,
            enabled=None,
            type_id=self.vtype.id,
        )
        self.assertEqual(page.total, 2)
        codes = {item.code for item in page.items}
        self.assertEqual(codes, {"110kv", "220kv"})

    def test_legacy_dimension_type_param_compat(self) -> None:
        """老接口传 dimension_type（code）字符串应按 code 匹配转 type_id 过滤。"""
        self._add_item(self.vtype.id, "110kv", "110千伏")
        self._add_item(self.ttype.id, "cat", "猫头塔")

        page = list_dimension_items(
            self.session,
            limit=50,
            offset=0,
            keyword=None,
            dimension_type="tower_type",
            enabled=None,
        )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.items[0].code, "cat")

    def test_tree_filters_by_type_id(self) -> None:
        self._add_item(self.vtype.id, "110kv", "110千伏")
        self._add_item(self.ttype.id, "cat", "猫头塔")

        tree = get_dimension_tree(self.session, type_id=self.ttype.id)
        self.assertEqual(len(tree), 1)
        self.assertEqual(tree[0].code, "cat")

    def test_type_code_duplicate_conflict(self) -> None:
        """(type_id, code) 组合查重：同类型下重复 code 应被拒绝。"""
        self._add_item(self.vtype.id, "110kv", "110千伏")
        duplicate = create_dimension_item(
            self.session,
            DimensionItemCreateRequest(type_id=self.vtype.id,  code="110kv", name="重复110千伏"),
            actor=self.actor,
        )
        self.assertIsNone(duplicate)

        # 不同类型允许相同 code
        other = create_dimension_item(
            self.session,
            DimensionItemCreateRequest(type_id=self.ttype.id,  code="110kv", name="塔型110千伏"),
            actor=self.actor,
        )
        self.assertIsNotNone(other)

    def test_update_type_id_rejects_invalid(self) -> None:
        self._add_item(self.vtype.id, "110kv", "110千伏")
        item = self.session.scalar(select(DimensionItem).where(DimensionItem.code == "110kv"))
        assert item is not None

        updated = update_dimension_item(
            self.session,
            item.id,
            DimensionItemUpdateRequest(type_id="nonexistent-type"),
            actor=self.actor,
        )
        # type_id 指向不存在类型 -> 拒绝
        self.assertIsNone(updated)

    def test_update_type_id_changes_type(self) -> None:
        self._add_item(self.vtype.id, "110kv", "110千伏")
        item = self.session.scalar(select(DimensionItem).where(DimensionItem.code == "110kv"))
        assert item is not None

        updated = update_dimension_item(
            self.session,
            item.id,
            DimensionItemUpdateRequest(type_id=self.ttype.id),
            actor=self.actor,
        )
        assert updated is not None
        self.assertEqual(updated.type_id, self.ttype.id)


if __name__ == "__main__":
    unittest.main()