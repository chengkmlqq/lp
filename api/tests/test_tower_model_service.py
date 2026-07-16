from __future__ import annotations

import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.app import models  # noqa: F401
from api.app.core.database import Base
from api.app.models.tower_model import TowerModel
from api.app.services.tower_model_service import list_tower_models


class TowerModelServiceTest(unittest.TestCase):
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

    def tearDown(self) -> None:
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_list_tower_models_applies_limit_and_offset(self) -> None:
        for index in range(5):
            self.session.add(
                TowerModel(
                    code=f"TM-{index}",
                    name=f"Tower Model {index}",
                    tower_type="直线",
                    is_enabled=True,
                    sort_order=index,
                )
            )
        self.session.commit()

        page = list_tower_models(
            self.session,
            limit=2,
            offset=1,
            keyword=None,
            enabled=None,
        )

        self.assertEqual(page.total, 5)
        self.assertEqual([item.code for item in page.items], ["TM-1", "TM-2"])

    def test_list_tower_models_filters_before_paginating(self) -> None:
        self.session.add_all(
            [
                TowerModel(code="A-ZX", name="直线模型 A", tower_type="直线", is_enabled=True, sort_order=1),
                TowerModel(code="B-NZ", name="耐张模型 B", tower_type="耐张", is_enabled=False, sort_order=2),
                TowerModel(code="C-ZX", name="直线模型 C", tower_type="直线", is_enabled=True, sort_order=3),
            ]
        )
        self.session.commit()

        page = list_tower_models(
            self.session,
            limit=1,
            offset=0,
            keyword="直线",
            enabled=True,
        )

        self.assertEqual(page.total, 2)
        self.assertEqual(len(page.items), 1)
        self.assertTrue(page.items[0].is_enabled)
        self.assertEqual(page.items[0].tower_type, "直线")


if __name__ == "__main__":
    unittest.main()
