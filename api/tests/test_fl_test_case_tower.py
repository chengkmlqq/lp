"""防雷计算用例「表单快照 → 托管计算塔」回归测试（离线，不需要 wine / ATP）。

覆盖需求：用例表单直接填「编辑杆塔」+「防雷计算」两套字段，不再绑定
测试线路 / 测试塔；保存时按快照自动托管一基计算塔，执行参数全量透传。
"""

from __future__ import annotations

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.line import Line
from app.models.line_tower import LineTower
from app.models.tower_circuit import TowerCircuit
from app.models.tower_profile import TowerProfile
from app.schemas.fl_test_set import (
    FlTestCaseCreateRequest,
    FlTestCaseUpdateRequest,
    FlTestSetCreateRequest,
)
from app.services import fl_test_set_service as service
from app.services import line_service
from app.services.fl_test_case_tower import MANAGED_LINE_PREFIX
from app.services.line_preparation_service import summarize_line_preparation


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _new_set(db: Session) -> str:
    created = service.create_set(
        db,
        payload=FlTestSetCreateRequest(category="fl_calc", name="115kV 回归集"),
        actor_user_id=None,
    )
    return str(created["id"])


def _case_payload() -> FlTestCaseCreateRequest:
    return FlTestCaseCreateRequest(
        name="115-ganzi-M123-普通计算",
        calc_kind="normal",
        params_json={
            "external_adapter": "wine",
            "tower": {
                "tower_no": "N1",
                "tower_type": "d115ganzi",
                "tower_model": "d115ganzi",
                "ground_resistance_ohm": 12.5,
                "lightning_density": 3.2,
                "slope_1": 0.0,
                "slope_2": 0.0,
                "voltage_kv": 115,
                "current_a": 25.109,
                "current_b": 3.62,
                "insulator_length_m": 1000,
            },
            "execution_options_json": {
                "fanji_naleishuiping_method": "atp",
                "raoji_naleishuiping_method": "atp",
                "fanji_tzl_method": "guicheng",
                "raoji_tzl_method": "egm",
                "current_waveform": "heidler",
                "flashover_method": "intersection",
                "altitude_correction": "none",
                "induced_voltage_formula": "formula1",
                "head_time_min_us": 2.6,
                "tail_time_min_us": 50,
                "binary_search": True,
            },
        },
        expected_json={"metrics": []},
    )


def test_case_form_snapshot_creates_managed_tower() -> None:
    db = _session()
    set_id = _new_set(db)
    created = service.create_case(db, set_id=set_id, payload=_case_payload(), actor_user_id=None)

    line = db.execute(select(Line).where(Line.id == created["line_id"])).scalar_one()
    assert line.code.startswith(MANAGED_LINE_PREFIX)
    assert line.voltage_kv == 115
    assert line.lightning_param_json["雷电流幅值a"] == 25.109

    towers = db.execute(select(LineTower).where(LineTower.line_id == line.id)).scalars().all()
    assert len(towers) == 1
    tower = towers[0]
    assert tower.tower_no == "N1"
    assert tower.tower_type == "d115ganzi"
    assert tower.ground_resistance_ohm == 12.5
    assert tower.lightning_density == 3.2

    profile = db.execute(select(TowerProfile).where(TowerProfile.tower_id == tower.id)).scalar_one()
    assert profile.current_a == 25.109
    assert profile.insulator_length_m == 1000
    circuits = db.execute(select(TowerCircuit).where(TowerCircuit.tower_id == tower.id)).scalars().all()
    assert len(circuits) == 1
    assert circuits[0].height_upper_m is not None

    # 线路准备状态门禁必须放行（否则 create_job 会 400）
    assert summarize_line_preparation(db, line)["all_ready"] is True

    # 执行参数全量透传、单塔语义不变
    test_set = service._get_set(db, set_id)
    case = service._get_case(db, created["id"])
    request = service._build_job_request(db, test_set, case)
    assert request.line_id == line.id
    assert request.job_type == "normal"
    assert request.execution_options_json["fanji_naleishuiping_method"] == "atp"
    assert request.execution_options_json["head_time_min_us"] == 2.6
    assert request.execution_options_json["selected_tower_ids"] == [tower.id]

    # 托管线路是内部载体，不应出现在业务线路列表里
    assert line_service.list_lines(db, keyword=None, limit=10).total == 0
    assert line_service.list_lines(db, keyword=None, limit=10, include_managed=True).total == 1


def test_case_update_refreshes_managed_tower_in_place() -> None:
    db = _session()
    set_id = _new_set(db)
    created = service.create_case(db, set_id=set_id, payload=_case_payload(), actor_user_id=None)
    line_id = created["line_id"]

    updated_params = _case_payload().model_dump()["params_json"]
    updated_params["tower"]["tower_no"] = "N2"
    updated_params["tower"]["ground_resistance_ohm"] = 30.0
    service.update_case(
        db,
        case_id=created["id"],
        payload=FlTestCaseUpdateRequest(name="改过的用例", params_json=updated_params),
        actor_user_id=None,
    )

    assert db.scalar(select(func.count()).select_from(Line)) == 1
    tower = db.execute(select(LineTower).where(LineTower.line_id == line_id)).scalar_one()
    assert tower.tower_no == "N2"
    assert tower.ground_resistance_ohm == 30.0
    assert service._get_case(db, created["id"]).name == "改过的用例"


def test_delete_case_cleans_unused_managed_line() -> None:
    db = _session()
    set_id = _new_set(db)
    created = service.create_case(db, set_id=set_id, payload=_case_payload(), actor_user_id=None)
    line_id = created["line_id"]
    service.delete_case(db, case_id=created["id"])
    assert db.execute(select(Line).where(Line.id == line_id)).scalar_one_or_none() is None
