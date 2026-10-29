"""维度种子单测：空库全播 / 幂等 / force 覆盖 / 禁用项 / 双库方言冒烟。

- 默认 SQLite 内存库（仿 test_seed_defaults_contract.DatabaseFixtureTestCase）。
- PG 实跑：TEST_DATABASE_URL 指向真实 PG 时执行（见 test_seed_on_postgresql）。
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.services.dimension_seed import (
    DIMENSION_ITEMS,
    DIMENSION_TYPES,
    seed_dimensions,
)
from app.models.dimension_item import DimensionItem
from app.models.dimension_type import DimensionType

EXPECTED_TYPE_COUNT = 13
EXPECTED_ITEM_COUNT = sum(len(items) for items in DIMENSION_ITEMS.values())


class DatabaseFixtureTestCase(unittest.TestCase):
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

    def tearDown(self) -> None:
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def seed(self, force: bool = False) -> dict[str, int]:
        with self.SessionLocal() as db:
            stats = seed_dimensions(db, force=force, operator="test")
            db.commit()
            return stats

    def counts(self) -> tuple[int, int]:
        with self.SessionLocal() as db:
            return (
                db.query(DimensionType).count(),
                db.query(DimensionItem).count(),
            )


class DimensionSeedSqliteTest(DatabaseFixtureTestCase):
    def test_empty_db_seeds_all_types_and_items(self) -> None:
        stats = self.seed()
        self.assertEqual(stats["created"], EXPECTED_TYPE_COUNT + EXPECTED_ITEM_COUNT)
        self.assertEqual(stats["updated"], 0)
        self.assertEqual(stats["skipped"], 0)
        types, items = self.counts()
        self.assertEqual(types, EXPECTED_TYPE_COUNT)
        self.assertEqual(items, EXPECTED_ITEM_COUNT)

    def test_seed_is_idempotent_on_second_run(self) -> None:
        self.seed()
        stats = self.seed()
        self.assertEqual(stats["created"], 0)
        self.assertEqual(stats["updated"], 0)
        self.assertEqual(stats["skipped"], EXPECTED_TYPE_COUNT + EXPECTED_ITEM_COUNT)

    def test_force_overwrites_manual_changes(self) -> None:
        self.seed()
        with self.SessionLocal() as db:
            row = db.query(DimensionType).filter_by(code="voltage_level").one()
            row.name = "手动改名"
            db.commit()
        stats = self.seed(force=True)
        self.assertGreater(stats["updated"], 0)
        with self.SessionLocal() as db:
            row = db.query(DimensionType).filter_by(code="voltage_level").one()
            self.assertEqual(row.name, "电压等级")

    def test_default_does_not_overwrite_manual_changes(self) -> None:
        self.seed()
        with self.SessionLocal() as db:
            row = db.query(DimensionType).filter_by(code="voltage_level").one()
            row.name = "手动改名"
            db.commit()
        self.seed()
        with self.SessionLocal() as db:
            row = db.query(DimensionType).filter_by(code="voltage_level").one()
            self.assertEqual(row.name, "手动改名")

    def test_disabled_items_seeded_as_disabled(self) -> None:
        self.seed()
        with self.SessionLocal() as db:
            risk = (
                db.query(DimensionItem)
                .join(DimensionType, DimensionItem.type_id == DimensionType.id)
                .filter(
                    DimensionType.code == "fl_analysis_job_type",
                    DimensionItem.code == "risk",
                )
                .one()
            )
            normal = (
                db.query(DimensionItem)
                .join(DimensionType, DimensionItem.type_id == DimensionType.id)
                .filter(
                    DimensionType.code == "fl_analysis_job_type",
                    DimensionItem.code == "normal",
                )
                .one()
            )
        self.assertFalse(risk.is_enabled)
        self.assertTrue(normal.is_enabled)

    def test_type_id_links_items(self) -> None:
        self.seed()
        with self.SessionLocal() as db:
            orphaned = (
                db.query(DimensionItem)
                .outerjoin(DimensionType, DimensionItem.type_id == DimensionType.id)
                .filter(DimensionType.id.is_(None))
                .count()
            )
        self.assertEqual(orphaned, 0)


class SeedDimensionsSchemaContractTest(unittest.TestCase):
    def test_type_codes_unique(self) -> None:
        codes = [t["code"] for t in DIMENSION_TYPES]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(len(DIMENSION_TYPES), EXPECTED_TYPE_COUNT)

    def test_item_codes_unique_within_type(self) -> None:
        for type_code, items in DIMENSION_ITEMS.items():
            codes = [i[0] for i in items]
            self.assertEqual(len(codes), len(set(codes)), f"{type_code} 值重复")

    def test_all_items_have_valid_type(self) -> None:
        type_codes = {t["code"] for t in DIMENSION_TYPES}
        self.assertTrue(set(DIMENSION_ITEMS).issubset(type_codes))


@unittest.skipUnless(
    os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql"),
    "需 TEST_DATABASE_URL 指向真实 PG（例：postgresql+psycopg://user:pwd@host/lp_test）",
)
class DimensionSeedPostgresTest(unittest.TestCase):
    """PG 真库实跑：空库播种 + 幂等 + 禁用项。运行前需确保测试库存在且为空。"""

    def setUp(self) -> None:
        self.engine = create_engine(os.environ["TEST_DATABASE_URL"])
        self.SessionLocal = sessionmaker(
            bind=self.engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
        Base.metadata.create_all(bind=self.engine)

    def tearDown(self) -> None:
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_pg_seed_and_idempotency(self) -> None:
        with self.SessionLocal() as db:
            stats = seed_dimensions(db, force=False, operator="pg-test")
            db.commit()
            self.assertEqual(stats["created"], EXPECTED_TYPE_COUNT + EXPECTED_ITEM_COUNT)
        with self.SessionLocal() as db:
            stats2 = seed_dimensions(db, force=False, operator="pg-test")
            db.commit()
            self.assertEqual(stats2["created"], 0)
            self.assertEqual(
                db.query(DimensionType).count(), EXPECTED_TYPE_COUNT
            )
            self.assertEqual(
                db.query(DimensionItem).count(), EXPECTED_ITEM_COUNT
            )


if __name__ == "__main__":
    unittest.main()