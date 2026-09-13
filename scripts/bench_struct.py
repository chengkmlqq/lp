"""验证 e57168b 双回路改动是否真的放行 1..6 档独立折半。
只测结构（phase_entries 档数、每档是否独立折半、是否收敛），不重跑全部 ATP 太久。
为省时, 复用 bench_final 的 resolve/参数, 但把 tolerance 调松让收敛更快。

运行（需 wine 引擎 + 数据库，故在 wine-worker 容器内）：
  docker cp scripts/bench_struct.py lp-deploy-wine-worker-1:/app/bench_struct.py
  docker exec -e PYTHONPATH=/app lp-deploy-wine-worker-1 python3 /app/bench_struct.py
"""
import time
from app.core.database import SessionLocal
from app.models.fl_analysis import FlAnalysisTowerSnapshot
from app.services.fl_analysis_external import (
    execute_multi_phase_binary_search_external,
    resolve_external_waveform_job,
    _circuit_count_for_snapshot,
)
from types import SimpleNamespace

db = SessionLocal()
real_snap = (
    db.query(FlAnalysisTowerSnapshot)
    .filter(FlAnalysisTowerSnapshot.tower_no == "P1")
    .order_by(FlAnalysisTowerSnapshot.create_date.desc())
    .first()
)
assert real_snap is not None, "无 P1 快照"
base_tower = dict(real_snap.base_tower_json or {})
profile = dict(real_snap.profile_json or {})

# 基准参数覆盖（同 bench_final）
cg = dict(base_tower.get("circuit_geometry_json") or {})
lw = dict(cg.get("lightning_wire") or {})
lw.update({"left_mid_distance_m": 12.4, "right_mid_distance_m": 12.4, "height_m": 73.5})
cg["lightning_wire"] = lw
circuits = dict(cg.get("circuits") or {})
for ci in ("I", "II"):
    c = dict(circuits.get(ci) or {})
    c["phase_height_m"] = {"upper": 65.5, "middle": 53.0, "lower": 42.0}
    c["spacing"] = {"upper": 12.0, "middle": 12.0, "lower": 12.0}
    circuits[ci] = c
cg["circuits"] = circuits
base_tower["circuit_geometry_json"] = cg
base_tower.update({
    "lightning_density": 2.8, "ground_resistance_ohm": 20,
    "span_small_m": 279, "span_large_m": 562, "slope_1": 0, "slope_2": 0, "altitude_m": 500,
})
profile.update({
    "shield_wire_height_m": 73.5, "insulator_length_m": 5945.0, "call_height_m": 42.0,
    "protection_angle_left_deg": 12.4, "protection_angle_right_deg": 12.4,
    "current_a": 25.109, "current_b": 3.62,
    "phase_sequence_1": "ABC", "phase_sequence_2": "ABC",
    "phase_sequence_3": "ABC", "phase_sequence_4": "ABC",
    "structure_kind": "耐张", "current_head_time_us": 2.0, "current_tail_time_us": 40.0,
    "tower_kind": "guxing",
})
payload = {"base_tower_json": base_tower, "profile_json": profile}

execution_options = {
    "current_waveform": "heidler", "flashover_method": "intersection",
    "altitude_correction": "none", "induced_voltage_formula": "formula1",
    "head_time_min_us": 2.0, "head_time_max_us": 2.0, "head_time_step_us": 0.1,
    "tail_time_min_us": 40.0, "tail_time_max_us": 40.0, "tail_time_step_us": 1.0,
    "fanji_naleishuiping_method": "atp", "raoji_naleishuiping_method": "atp",
    "binary_search": True, "binary_search_low_ka": 0.1, "binary_search_high_ka": 2000.0,
    "binary_search_tolerance_ka": 0.1, "binary_search_max_iterations": 20,
}

job = SimpleNamespace(id="bench-struct", job_name="struct-test", job_type="tongtiao", external_adapter="atp")
snapshot = FlAnalysisTowerSnapshot(
    id="bench-struct-snap", job_id=job.id, run_id="bench", tower_id="t", seq_no=1,
    tower_no="P1", tower_model="500-MC31S-DJC2-42", tower_type="s500guxing",
    base_tower_json=base_tower, profile_json=profile,
)

print("电路数(_circuit_count_for_snapshot):", _circuit_count_for_snapshot(snapshot))
resolved = resolve_external_waveform_job(
    db, external_adapter="atp",
    adapter_config_json={"asset_id": "c511aa79659d406a8c015e87e808c441"},
    tower_type="s500guxing", line_voltage_kv=500, scene_type="fanji",
)
# geometry_layers 覆盖
profile.setdefault("geometry_layers_json", {})
gl = dict(profile.get("geometry_layers_json") or {})
layer_i = dict(gl.get("I") or {})
layer_i["phase_height_m"] = {"upper": 65.5, "middle": 53.0, "lower": 42.0}
layer_i["phase_spacing_m"] = {"upper": 12.0, "middle": 12.0, "lower": 12.0}
gl["I"] = layer_i
gl["lightning_wire"] = {"left_mid_distance_m": 12.4, "right_mid_distance_m": 12.4, "height_m": 73.5}
profile["geometry_layers_json"] = gl
snapshot.profile_json = profile

from app.services.fl_analysis_rules import grade_normal_snapshot_payload
baseline = grade_normal_snapshot_payload(payload, execution_options=execution_options)

# 关键：不显式传 max_phases（走默认6），由 _circuit_count_for_snapshot 决定
result = execute_multi_phase_binary_search_external(
    resolved, db=db, job=job, snapshot=snapshot,
    execution_options=execution_options, baseline_result=baseline, payload=payload,
)
mbs = result.result_json.get("multi_phase_binary_search") or {}
entries = mbs.get("phase_entries") or []
print("\n=== 多相折半结构（不传 max_phases，靠塔型判定）===")
print("phase_entries 档数:", len(entries), "| ready 数:", mbs.get("ready_count"))
for e in entries:
    sh = e.get("search_history") or []
    hist = ", ".join(f"{h.get('current_ka', '-')}->{h.get('flashover_count', '-')}" for h in sh[-4:]) or "(无历史)"
    print(f"  {e.get('label'):5s} converged={e.get('converged')} withstand={e.get('counterstrike_withstand_ka')} iter={len(sh)} 末段:{hist}")
db.close()