"""LP-133：机组型号 / 叶片型号映射的 schema 校验、CRUD 服务与接口测试。"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.api.v1.wind_model_mapping import router as wind_model_mapping_router
from app.core.database import Base, get_db
from app.core.dependencies import CurrentUser, get_current_user
from app.models.user import User
from app.schemas.wind_model_mapping import (
    WindBladeModelCreateRequest,
    WindTurbineModelCreateRequest,
)
from app.services import wind_model_mapping_service as service


class _ModelMappingTestBase(unittest.TestCase):
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
        self.session: Session = self.SessionLocal()

    def tearDown(self) -> None:
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()


class WindModelMappingSchemaTest(unittest.TestCase):
    def test_rejects_non_positive_and_non_finite_values(self) -> None:
        for bad_value in (0, -1, float("inf"), float("-inf"), float("nan")):
            with self.assertRaises(ValidationError):
                WindTurbineModelCreateRequest(
                    code="WT-1", name="1.5MW", hub_height_m=bad_value
                )
            with self.assertRaises(ValidationError):
                WindBladeModelCreateRequest(
                    code="BL-1", name="56.6m", blade_length_m=bad_value
                )

    def test_rejects_blank_name_and_strips_code(self) -> None:
        with self.assertRaises(ValidationError):
            WindTurbineModelCreateRequest(code="WT-1", name="   ", hub_height_m=90)
        payload = WindTurbineModelCreateRequest(
            code="  WT-1  ", name=" 1.5MW ", hub_height_m=90
        )
        self.assertEqual(payload.code, "WT-1")
        self.assertEqual(payload.name, "1.5MW")


class WindModelMappingServiceTest(_ModelMappingTestBase):
    def test_create_list_and_filter_turbine_models(self) -> None:
        service.create_wind_turbine_model(
            self.session,
            WindTurbineModelCreateRequest(code="WT-A", name="A", hub_height_m=90, sort_order=2),
            actor_user_id="u1",
        )
        service.create_wind_turbine_model(
            self.session,
            WindTurbineModelCreateRequest(
                code="WT-B", name="B", hub_height_m=105, is_enabled=False, sort_order=1
            ),
            actor_user_id="u1",
        )

        page = service.list_wind_turbine_models(
            self.session, limit=50, offset=0, keyword=None, enabled=None
        )
        self.assertEqual(page.total, 2)
        self.assertEqual([item.code for item in page.items], ["WT-B", "WT-A"])

        enabled_page = service.list_wind_turbine_models(
            self.session, limit=50, offset=0, keyword=None, enabled=True
        )
        self.assertEqual([item.code for item in enabled_page.items], ["WT-A"])

        keyword_page = service.list_wind_turbine_models(
            self.session, limit=50, offset=0, keyword="wt-b", enabled=None
        )
        self.assertEqual([item.code for item in keyword_page.items], ["WT-B"])

    def test_pagination_applies_after_filters(self) -> None:
        for index in range(5):
            service.create_wind_blade_model(
                self.session,
                WindBladeModelCreateRequest(
                    code=f"BL-{index}", name=f"Blade {index}", blade_length_m=50 + index,
                    sort_order=index,
                ),
                actor_user_id="u1",
            )
        page = service.list_wind_blade_models(
            self.session, limit=2, offset=1, keyword=None, enabled=None
        )
        self.assertEqual(page.total, 5)
        self.assertEqual([item.code for item in page.items], ["BL-1", "BL-2"])

    def test_duplicate_code_is_rejected(self) -> None:
        payload = WindTurbineModelCreateRequest(code="WT-A", name="A", hub_height_m=90)
        service.create_wind_turbine_model(self.session, payload, actor_user_id="u1")
        with self.assertRaises(HTTPException) as ctx:
            service.create_wind_turbine_model(self.session, payload, actor_user_id="u1")
        self.assertEqual(ctx.exception.status_code, 409)

        blade = WindBladeModelCreateRequest(code="BL-A", name="A", blade_length_m=60)
        service.create_wind_blade_model(self.session, blade, actor_user_id="u1")
        with self.assertRaises(HTTPException) as ctx:
            service.create_wind_blade_model(self.session, blade, actor_user_id="u1")
        self.assertEqual(ctx.exception.status_code, 409)

    def test_update_and_delete_turbine_model(self) -> None:
        created = service.create_wind_turbine_model(
            self.session,
            WindTurbineModelCreateRequest(code="WT-A", name="A", hub_height_m=90),
            actor_user_id="u1",
        )
        service.create_wind_turbine_model(
            self.session,
            WindTurbineModelCreateRequest(code="WT-B", name="B", hub_height_m=100),
            actor_user_id="u1",
        )

        from app.schemas.wind_model_mapping import WindTurbineModelUpdateRequest

        updated = service.update_wind_turbine_model(
            self.session,
            created.id,
            WindTurbineModelUpdateRequest(name="A2", hub_height_m=95, is_enabled=False),
            actor_user_id="u2",
        )
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.name, "A2")
        self.assertEqual(updated.hub_height_m, 95)
        self.assertFalse(updated.is_enabled)
        self.assertEqual(updated.update_user, "u2")

        with self.assertRaises(HTTPException) as ctx:
            service.update_wind_turbine_model(
                self.session,
                created.id,
                WindTurbineModelUpdateRequest(code="WT-B"),
                actor_user_id="u2",
            )
        self.assertEqual(ctx.exception.status_code, 409)

        self.assertTrue(service.delete_wind_turbine_model(self.session, created.id))
        self.assertFalse(service.delete_wind_turbine_model(self.session, created.id))

    def test_update_missing_model_returns_none(self) -> None:
        from app.schemas.wind_model_mapping import WindBladeModelUpdateRequest

        self.assertIsNone(
            service.update_wind_blade_model(
                self.session,
                "missing",
                WindBladeModelUpdateRequest(name="x"),
                actor_user_id="u1",
            )
        )
        self.assertFalse(service.delete_wind_blade_model(self.session, "missing"))


def _current_user(uid: str = "admin-1") -> CurrentUser:
    return CurrentUser(
        user=User(
            id=uid,
            email="admin@example.com",
            username="admin",
            password_hash="secret",
            status="ENABLED",
        ),
        role_codes={"admin"},
        permission_codes={"wind_data_prep.manage"},
    )


class WindModelMappingApiTest(_ModelMappingTestBase):
    def setUp(self) -> None:
        super().setUp()
        app = FastAPI()
        app.include_router(wind_model_mapping_router, prefix="/api/v1")

        def _override_db():
            yield self.session

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_user] = lambda: _current_user()
        self.client = TestClient(app)

    def test_crud_round_trip_for_both_model_kinds(self) -> None:
        created = self.client.post(
            "/api/v1/wind-models/turbines",
            json={"code": "WT-1", "name": "1.5MW", "hub_height_m": 90},
        )
        self.assertEqual(created.status_code, 200, created.text)
        model_id = created.json()["id"]

        created_blade = self.client.post(
            "/api/v1/wind-models/blades",
            json={"code": "BL-1", "name": "56.6m", "blade_length_m": 56.6},
        )
        self.assertEqual(created_blade.status_code, 200, created_blade.text)

        listing = self.client.get("/api/v1/wind-models/turbines", params={"enabled": True})
        self.assertEqual(listing.status_code, 200, listing.text)
        self.assertEqual(listing.json()["total"], 1)
        self.assertEqual(listing.json()["items"][0]["hub_height_m"], 90)

        patched = self.client.patch(
            f"/api/v1/wind-models/turbines/{model_id}",
            json={"is_enabled": False, "hub_height_m": 100.5},
        )
        self.assertEqual(patched.status_code, 200, patched.text)
        self.assertFalse(patched.json()["is_enabled"])

        self.assertEqual(
            self.client.delete(f"/api/v1/wind-models/turbines/{model_id}").status_code, 200
        )
        self.assertEqual(
            self.client.delete(f"/api/v1/wind-models/turbines/{model_id}").status_code, 404
        )

    def test_invalid_payload_is_422(self) -> None:
        response = self.client.post(
            "/api/v1/wind-models/blades",
            json={"code": "BL-X", "name": "bad", "blade_length_m": 0},
        )
        self.assertEqual(response.status_code, 422)

    def test_duplicate_code_is_409(self) -> None:
        body = {"code": "WT-DUP", "name": "dup", "hub_height_m": 80}
        self.assertEqual(
            self.client.post("/api/v1/wind-models/turbines", json=body).status_code, 200
        )
        self.assertEqual(
            self.client.post("/api/v1/wind-models/turbines", json=body).status_code, 409
        )


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
