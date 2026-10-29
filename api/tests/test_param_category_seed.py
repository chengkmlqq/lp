"""系统参数分类种子单测：空库建分类/归类 / 幂等 / force 覆盖 / 不覆盖手动分类。

默认 SQLite 内存库。PG 实跑：TEST_DATABASE_URL 指向真实 PG 时执行。
"""

from __future__ import annotations

import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.param_category import SystemParamCategory
from app.models.system_param import SystemParam
from app.services.param_category_seed import PARAM_CATEGORIES, seed_param_categories

EXPECTED_CATEGORY_COUNT = len(PARAM_CATEGORIES)


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
            stats = seed_param_categories(db, force=force, operator="test")
            db.commit()
            return stats

    def category_ids(self) -> dict[str, int]:
        with self.SessionLocal() as db:
            return {row.name: row.id for row in db.query(SystemParamCategory).all()}


class ParamCategorySeedSqliteTest(DatabaseFixtureTestCase):
    def test_empty_db_creates_all_categories(self) -> None:
        stats = self.seed()
        self.assertEqual(stats["categories_created"], EXPECTED_CATEGORY_COUNT)
        self.assertEqual(stats["params_mapped"], 0)
        self.assertEqual(len(self.category_ids()), EXPECTED_CATEGORY_COUNT)

    def test_seed_maps_params_by_prefix(self) -> None:
        with self.SessionLocal() as db:
            db.add_all([
                SystemParam(param_key="ai_chat.model", param_name="AI模型", param_value="gpt-4o"),
                SystemParam(param_key="tianditu.enabled", param_name="天地图启用", param_value="true"),
                SystemParam(param_key="auth.captcha.enabled", param_name="验证码", param_value="true"),
                SystemParam(param_key="matlab_engine.modules", param_name="引擎模块", param_value="[]"),
                SystemParam(param_key="unknown.xyz", param_name="未知", param_value="1"),
            ])
            db.commit()
        stats = self.seed()
        self.assertEqual(stats["params_mapped"], 4)
        with self.SessionLocal() as db:
            cats = self.category_ids()
            ai = db.query(SystemParam).filter_by(param_key="ai_chat.model").one()
            ti = db.query(SystemParam).filter_by(param_key="tianditu.enabled").one()
            au = db.query(SystemParam).filter_by(param_key="auth.captcha.enabled").one()
            ml = db.query(SystemParam).filter_by(param_key="matlab_engine.modules").one()
            un = db.query(SystemParam).filter_by(param_key="unknown.xyz").one()
            self.assertEqual(ai.category_id, cats["AI 智能问答"])
            self.assertEqual(ti.category_id, cats["天地图底图"])
            self.assertEqual(au.category_id, cats["登录认证"])
            self.assertEqual(ml.category_id, cats["MATLAB 引擎"])
            self.assertIsNone(un.category_id)

    def test_seed_is_idempotent(self) -> None:
        with self.SessionLocal() as db:
            db.add(SystemParam(param_key="tianditu.tk", param_name="Key", param_value=""))
            db.commit()
        self.seed()
        stats = self.seed()
        self.assertEqual(stats["categories_created"], 0)
        self.assertEqual(stats["params_mapped"], 0)

    def test_default_does_not_overwrite_manual_category(self) -> None:
        with self.SessionLocal() as db:
            db.add(SystemParam(param_key="tianditu.enabled", param_name="启用", param_value="true"))
            db.commit()
        self.seed()
        with self.SessionLocal() as db:
            cats = self.category_ids()
            p = db.query(SystemParam).filter_by(param_key="tianditu.enabled").one()
            # 模拟管理员手动改挂到别的分类
            p.category_id = cats["登录认证"]
            db.commit()
        self.seed()
        with self.SessionLocal() as db:
            cats = self.category_ids()
            p = db.query(SystemParam).filter_by(param_key="tianditu.enabled").one()
            self.assertEqual(p.category_id, cats["登录认证"])

    def test_force_overwrites_manual_category(self) -> None:
        with self.SessionLocal() as db:
            db.add(SystemParam(param_key="tianditu.enabled", param_name="启用", param_value="true"))
            db.commit()
        self.seed()
        with self.SessionLocal() as db:
            cats = self.category_ids()
            p = db.query(SystemParam).filter_by(param_key="tianditu.enabled").one()
            p.category_id = cats["登录认证"]
            db.commit()
        stats = self.seed(force=True)
        self.assertEqual(stats["params_mapped"], 1)
        with self.SessionLocal() as db:
            cats = self.category_ids()
            p = db.query(SystemParam).filter_by(param_key="tianditu.enabled").one()
            self.assertEqual(p.category_id, cats["天地图底图"])


@unittest.skipUnless(
    os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql"),
    "需 TEST_DATABASE_URL 指向真实 PG（例：postgresql+psycopg://user:pwd@host/lp_test）",
)
class ParamCategorySeedPostgresTest(unittest.TestCase):
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
            stats = seed_param_categories(db, force=False, operator="pg-test")
            db.commit()
            self.assertEqual(stats["categories_created"], EXPECTED_CATEGORY_COUNT)
        with self.SessionLocal() as db:
            stats2 = seed_param_categories(db, force=False, operator="pg-test")
            db.commit()
            self.assertEqual(stats2["categories_created"], 0)
            self.assertEqual(
                db.query(SystemParamCategory).count(), EXPECTED_CATEGORY_COUNT
            )


if __name__ == "__main__":
    unittest.main()