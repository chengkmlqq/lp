from __future__ import annotations

from app.services.ws_event_bridge import publish_ws_event_from_worker
from app.tasks import lightning_tasks as lt


# ---------------------------------------------------------------------------
# ws_event_bridge —— worker 侧事件写入 Redis Stream
# ---------------------------------------------------------------------------
def test_publish_ws_event_from_worker_xadd(monkeypatch) -> None:
    xadd_calls: list[tuple] = []
    expire_calls: list[tuple] = []

    class FakeClient:
        def xadd(self, stream, fields, maxlen=None):
            xadd_calls.append((stream, fields, maxlen))
            return "1-0"

        def expire(self, stream, seconds):
            expire_calls.append((stream, seconds))

    monkeypatch.setattr(
        "app.services.ws_event_bridge._redis_client",
        lambda: FakeClient(),
    )
    publish_ws_event_from_worker(
        "admin.lightning-distribution",
        name="distribution.import_started",
        payload={"distribution_id": "d1", "stage": "parsing", "progress": 5},
        requires_refetch=["/api/v1/lightning-currents/distributions"],
        dedupe_key="distribution.import_started:d1",
    )

    assert len(xadd_calls) == 1
    stream, fields, maxlen = xadd_calls[0]
    assert stream == "ws_events"
    assert maxlen == 2000
    assert "topic" in fields
    assert fields["topic"] == "admin.lightning-distribution"
    assert "event" in fields
    assert "distribution.import_started" in fields["event"]
    assert "distribution_id" in fields["event"]
    assert expire_calls == [("ws_events", 3600)]


def test_publish_ws_event_from_worker_swallows_redis_error(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("redis down")

    monkeypatch.setattr("app.services.ws_event_bridge._redis_client", boom)
    # 不应抛出
    publish_ws_event_from_worker(
        "admin.lightning-distribution",
        name="distribution.import_started",
        payload={"distribution_id": "d1"},
    )


# ---------------------------------------------------------------------------
# lightning_tasks —— 任务侧推送辅助
# ---------------------------------------------------------------------------
def test_publish_distribution_event_routes_via_bridge(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_publish(topic, *, name, payload, requires_refetch=None, dedupe_key=None):
        calls.append({
            "topic": topic,
            "name": name,
            "payload": payload,
            "requires_refetch": requires_refetch,
            "dedupe_key": dedupe_key,
        })

    monkeypatch.setattr(
        "app.services.ws_event_bridge.publish_ws_event_from_worker",
        fake_publish,
    )
    lt._publish_distribution_event(
        "distribution.import_completed",
        {"distribution_id": "d1", "status": "completed", "valid_count": 5},
    )
    assert len(calls) == 1
    call = calls[0]
    assert call["topic"] == "admin.lightning-distribution"
    assert call["name"] == "distribution.import_completed"
    assert call["payload"]["distribution_id"] == "d1"
    assert call["requires_refetch"] == ["/api/v1/lightning-currents/distributions"]
    assert call["dedupe_key"] == "distribution.import_completed:d1"


def test_publish_amplitude_event_routes_via_bridge(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_publish(topic, *, name, payload, requires_refetch=None, dedupe_key=None):
        calls.append({
            "topic": topic,
            "name": name,
            "payload": payload,
            "requires_refetch": requires_refetch,
            "dedupe_key": dedupe_key,
        })

    monkeypatch.setattr(
        "app.services.ws_event_bridge.publish_ws_event_from_worker",
        fake_publish,
    )
    lt._publish_amplitude_event(
        "amplitude.import_progress",
        {"amplitude_id": "a1", "progress": 70},
    )
    assert len(calls) == 1
    call = calls[0]
    assert call["topic"] == "admin.lightning-amplitude"
    assert call["name"] == "amplitude.import_progress"
    assert call["payload"]["amplitude_id"] == "a1"
    assert call["requires_refetch"] == ["/api/v1/lightning-currents/amplitudes"]
    assert call["dedupe_key"] == "amplitude.import_progress:a1"
