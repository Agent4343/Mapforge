import pytest

from app.services.overpass_health import OverpassEndpointHealth


def test_prefers_available_endpoints_when_one_is_cooling():
    now = {"t": 100.0}
    health = OverpassEndpointHealth(
        failure_threshold=2,
        base_cooldown_s=20.0,
        max_cooldown_s=60.0,
        now_fn=lambda: now["t"],
    )
    endpoints = ["a", "b", "c"]

    health.record_failure("a", reason="timeout")
    health.record_failure("a", reason="timeout")
    ordered = health.get_endpoint_order(endpoints, service="test")

    assert "a" not in ordered
    assert ordered == ["b", "c"]


def test_probe_one_endpoint_when_all_are_cooling():
    now = {"t": 50.0}
    health = OverpassEndpointHealth(
        failure_threshold=1,
        base_cooldown_s=30.0,
        max_cooldown_s=30.0,
        now_fn=lambda: now["t"],
    )
    endpoints = ["a", "b"]

    health.record_failure("a", reason="http_429")
    health.record_failure("b", reason="http_429")
    ordered = health.get_endpoint_order(endpoints, service="test")

    assert len(ordered) == 1
    assert ordered[0] in endpoints


def test_success_clears_cooldown_and_consecutive_failures():
    now = {"t": 0.0}
    health = OverpassEndpointHealth(
        failure_threshold=1,
        base_cooldown_s=10.0,
        max_cooldown_s=40.0,
        now_fn=lambda: now["t"],
    )
    endpoint = "a"

    health.record_failure(endpoint, reason="timeout")
    state = health.get_state_snapshot(endpoint)
    assert state["is_cooling"] is True
    assert state["consecutive_failures"] == 1

    health.record_success(endpoint, latency_s=1.2)
    state = health.get_state_snapshot(endpoint)
    assert state["is_cooling"] is False
    assert state["consecutive_failures"] == 0
    assert state["success_streak"] == 1
    assert state["avg_latency_s"] == pytest.approx(1.2, abs=1e-6)


def test_scoring_prefers_healthier_endpoint():
    now = {"t": 10.0}
    health = OverpassEndpointHealth(
        failure_threshold=3,
        base_cooldown_s=15.0,
        max_cooldown_s=60.0,
        now_fn=lambda: now["t"],
    )

    health.record_success("fast-good", latency_s=0.5)
    health.record_success("fast-good", latency_s=0.7)
    health.record_failure("slow-bad", reason="timeout")
    health.record_success("slow-bad", latency_s=5.0)

    ordered = health.get_endpoint_order(["slow-bad", "fast-good"], service="test")
    assert ordered[0] == "fast-good"
