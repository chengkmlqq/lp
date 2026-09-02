from __future__ import annotations

from app.tasks import fault_diagnosis_tasks as fdt


# ---------------------------------------------------------------------------
# fault_diagnosis_tasks._update_progress —— WS 事件 payload 语义
# ---------------------------------------------------------------------------
# 真实进度事件（progress>=0）必须携带 progress 字段；阶段事件（progress<0，
# step_callback 触发）只带 step/status，不携带 progress，避免前端把阶段事件
# 误当真实进度把进度条重置为 0（旧逻辑 max(-1,0)=0）。
def test_update_progress_real_progress_includes_progress_field(monkeypatch) -> None:
    captured: list[dict] = []

    def fake_publish(event_name, payload):
        captured.append(payload)

    monkeypatch.setattr(fdt, "_publish_fault_analysis_event", fake_publish)
    # progress>=0 会尝试写库：SessionLocal 返回 None 时查询抛异常被吞掉，不影响 payload 发布
    monkeypatch.setattr(
        "app.core.database.SessionLocal",
        lambda: None,
    )
    fdt._update_progress("aid-1", 30, "processing")
    assert captured, "真实进度事件应发布 WS 事件"
    payload = captured[0]
    assert payload["analysis_id"] == "aid-1"
    assert payload["progress"] == 30
    assert payload["status"] == "processing"
    assert "step" not in payload


def test_update_progress_step_event_omits_progress_field(monkeypatch) -> None:
    captured: list[dict] = []

    def fake_publish(event_name, payload):
        captured.append(payload)

    monkeypatch.setattr(fdt, "_publish_fault_analysis_event", fake_publish)
    # progress<0：不写库，只发布阶段事件
    fdt._update_progress("aid-1", -1, "processing", step="开始收集输入")
    assert captured, "阶段事件应发布 WS 事件"
    payload = captured[0]
    assert "progress" not in payload, "阶段事件不得携带 progress 字段"
    assert payload["step"] == "开始收集输入"
    assert payload["analysis_id"] == "aid-1"


def test_update_progress_real_progress_with_step_keeps_progress(monkeypatch) -> None:
    """90% 的「生成Word报告」事件同时携带真实进度与阶段描述。"""
    captured: list[dict] = []

    def fake_publish(event_name, payload):
        captured.append(payload)

    monkeypatch.setattr(fdt, "_publish_fault_analysis_event", fake_publish)
    monkeypatch.setattr(
        "app.core.database.SessionLocal",
        lambda: None,
    )
    fdt._update_progress("aid-1", 90, "processing", step="生成Word报告")
    assert captured
    payload = captured[0]
    assert payload["progress"] == 90
    assert payload["step"] == "生成Word报告"
