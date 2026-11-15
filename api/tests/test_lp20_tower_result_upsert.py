"""LP-20：同塔回写 tower_lightning_result 改为数据库级幂等 upsert + 失败文案分类。

刻意不用 pytest fixture（兼容桩驱动），用普通函数 + SQLite 内存库自测：
  - 回写不再读 ORM 关系缓存（lazy=selectin 的 lightning_result=None），
    连续/两次独立回写都幂等收敛到一行，后完成的结果覆盖先完成的，不抛唯一键冲突；
  - 「全部塔失败」文案把结果落库唯一键冲突单独归类，不再笼统并入「ATP 模型不可运行」。
"""
from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
# 注册 FK 目标表(power_line / power_line_tower)到 metadata，使 create_all 能解析外键。
from app.models.line import Line  # noqa: F401
from app.models.line_tower import LineTower  # noqa: F401
from app.models.tower_analysis import TowerAnalysis  # noqa: F401
from app.models.tower_circuit import TowerCircuit  # noqa: F401
from app.models.tower_lightning_result import TowerLightningResult
from app.models.tower_profile import TowerProfile  # noqa: F401
from app.services import fl_analysis_service as svc
from app.models.base import utcnow


def _session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[TowerLightningResult.__table__])
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def _session_factory_full():
    """含 LineTower 各 selectin 关系表，供真实 ORM 对象(db.get)的场景使用。"""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[
        Line.__table__, LineTower.__table__, TowerProfile.__table__,
        TowerCircuit.__table__, TowerLightningResult.__table__, TowerAnalysis.__table__,
    ])
    return sessionmaker(bind=engine, autocommit=False, autoflush=True, expire_on_commit=False)


def _graded(risk_level, withstand_ka, trip_rate):
    return {
        "stroke_mode": 2,
        "counterstrike_withstand_ka": withstand_ka,
        "counterstrike_trip_rate": trip_rate,
        "shielding_withstand_ka": withstand_ka / 2,
        "shielding_trip_rate": trip_rate / 2,
        "angle_deg": 12.5,
        "current_a": 31.0,
        "current_b": 2.6,
        "risk_level": risk_level,
    }


def _rows(db, tower_id):
    return db.execute(
        select(TowerLightningResult).where(TowerLightningResult.tower_id == tower_id)
    ).scalars().all()


def test_upsert_is_idempotent_and_last_writer_wins():
    Session = _session_factory()
    # 用 SimpleNamespace 模拟「session 里缓存 lightning_result=None 的塔」。
    # 修复后的实现完全不读该 ORM 关系，故仍应幂等落库、不撞唯一键。
    tower = SimpleNamespace(id="tower-lp20", lightning_result=None)
    db = Session()
    try:
        svc._upsert_tower_lightning_result_from_graded(
            db, tower=tower, graded=_graded("high", 100.0, 0.02), actor_user_id="normal"
        )
        db.commit()
        svc._upsert_tower_lightning_result_from_graded(
            db, tower=tower, graded=_graded("low", 150.0, 0.01), actor_user_id="tongtiao"
        )
        db.commit()

        # 实现未依赖、也未篡改 ORM 关系缓存；结果却已正确落库。
        assert tower.lightning_result is None
        rows = _rows(db, tower.id)
        assert len(rows) == 1, "一塔一行"
        row = rows[0]
        assert row.risk_level == "low"  # 后完成的 tongtiao 覆盖先完成的 normal
        assert row.counterstroke_withstand_ka == 150.0
        assert row.counterstroke_trip_rate == 0.01
        assert row.create_date is not None
        assert row.update_date is not None
    finally:
        db.close()


def test_upsert_two_sessions_converge_to_one_row():
    Session = _session_factory()
    tid = "tower-lp20-two"
    # 模拟两个独立任务(各用独立 session)：先后回写同一塔，都不应抛 UniqueViolation。
    for risk, ka, rate in [("high", 100.0, 0.02), ("low", 150.0, 0.01)]:
        db = Session()
        try:
            svc._upsert_tower_lightning_result_from_graded(
                db,
                tower=SimpleNamespace(id=tid, lightning_result=None),
                graded=_graded(risk, ka, rate),
                actor_user_id="worker",
            )
            db.commit()
        finally:
            db.close()

    db = Session()
    try:
        rows = _rows(db, tid)
        assert len(rows) == 1
        assert rows[0].risk_level == "low"
        assert rows[0].counterstroke_withstand_ka == 150.0
    finally:
        db.close()


def test_upsert_with_real_tower_orm_object_keeps_one_row():
    # 贴近真实调用方：db.get(LineTower) 加载(lightning_result 为 selectin 关系)，
    # 修改塔标量字段后回写。验证 Core INSERT 与 delete-orphan/cascade 关系在
    # autoflush+commit 下不会删除或复制结果行（曾担心的隐蔽回归点）。
    Session = _session_factory_full()
    seed = Session()
    try:
        line = Line(code="L-LP20", name="LP20测试线路", voltage_kv=330)
        seed.add(line)
        seed.flush()
        tower = LineTower(line_id=line.id, seq_no=1, tower_no="T001")
        seed.add(tower)
        seed.commit()
        tower_id = tower.id
    finally:
        seed.close()

    for risk, ka, rate in [("high", 100.0, 0.02), ("low", 150.0, 0.01)]:
        db = Session()
        try:
            t = db.get(LineTower, tower_id)
            t.risk_level = risk
            t.update_date = utcnow()
            t.update_user = "worker"
            svc._upsert_tower_lightning_result_from_graded(
                db, tower=t, graded=_graded(risk, ka, rate), actor_user_id="worker"
            )
            db.commit()
        finally:
            db.close()

    db = Session()
    try:
        rows = _rows(db, tower_id)
        assert len(rows) == 1, "一塔一行，autoflush 未误删/复制"
        assert rows[0].risk_level == "low"
        assert rows[0].counterstroke_withstand_ka == 150.0
    finally:
        db.close()


def test_failure_message_classifies_unique_key_conflict():
    conflict = (
        "IntegrityError: (psycopg.errors.UniqueViolation) duplicate key value "
        'violates unique constraint "uq_tower_lightning_result_tower_id"'
    )
    msg = svc._all_towers_failed_message(1, [conflict])
    assert "结果落库阶段" in msg
    assert "uq_tower_lightning_result_tower_id" in msg
    assert "与 ATP 引擎无关" in msg
    assert "ATP 模型不可运行" not in msg  # 不再误并入引擎类原因
    assert "duplicate key" in msg  # 真实报错透出

    # 非落库冲突(EGM 几何)仍走 LP-19 两阶段分类，不误判为落库冲突
    egm = "ValueError: 塔型 guxing 期望 2 回路，但塔几何实际只有 1 回路 —— 塔型与几何不一致"
    msg2 = svc._all_towers_failed_message(1, [egm])
    assert "引擎执行失败" in msg2
    assert "结果计算阶段失败" in msg2
    assert "结果落库阶段" not in msg2
