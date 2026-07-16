from __future__ import annotations

import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.app import models  # noqa: F401
from api.app.core.database import Base
from api.app.models.system_param import SystemParam
from api.app.services.system_param_service import list_system_params


class SystemParamServiceTest(unittest.TestCase):
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

    def test_list_system_params_applies_limit_and_offset(self) -> None:
        for index in range(5):
            self.session.add(
                SystemParam(
                    param_key=f"param_{index}",
                    param_name=f"Param {index}",
                    param_value=f"value-{index}",
                    description=f"description-{index}",
                    status="enabled",
                )
            )
        self.session.commit()

        page = list_system_params(
            self.session,
            limit=2,
            offset=1,
            keyword=None,
            status_filter=None,
        )

        self.assertEqual(page.total, 5)
        self.assertEqual(len(page.items), 2)

    def test_list_system_params_filters_before_paginating(self) -> None:
        self.session.add_all(
            [
                SystemParam(param_key="enabled_first", param_name="Enabled First", status="enabled"),
                SystemParam(param_key="disabled_first", param_name="Disabled First", status="disabled"),
                SystemParam(param_key="enabled_second", param_name="Enabled Second", status="enabled"),
            ]
        )
        self.session.commit()

        page = list_system_params(
            self.session,
            limit=1,
            offset=0,
            keyword="enabled",
            status_filter="enabled",
        )

        self.assertEqual(page.total, 2)
        self.assertEqual(len(page.items), 1)
        self.assertEqual(page.items[0].status, "enabled")


if __name__ == "__main__":
    unittest.main()
