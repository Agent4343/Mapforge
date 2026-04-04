"""Shared Overpass endpoint health scoring and circuit-breaker logic."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from app.logging_config import log


@dataclass
class _EndpointState:
    successes: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    success_streak: int = 0
    avg_latency_s: float | None = None
    cooldown_until_ts: float = 0.0
    last_failure_reason: str = ""


class OverpassEndpointHealth:
    """Tracks endpoint reliability and temporarily cools down failing nodes."""

    def __init__(
        self,
        *,
        failure_threshold: int = 2,
        base_cooldown_s: float = 20.0,
        max_cooldown_s: float = 180.0,
        cooldown_backoff: float = 2.0,
        latency_alpha: float = 0.25,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        self.failure_threshold = max(1, failure_threshold)
        self.base_cooldown_s = max(1.0, base_cooldown_s)
        self.max_cooldown_s = max(self.base_cooldown_s, max_cooldown_s)
        self.cooldown_backoff = max(1.1, cooldown_backoff)
        self.latency_alpha = min(max(latency_alpha, 0.05), 1.0)
        self._now_fn = now_fn or time.monotonic
        self._lock = threading.Lock()
        self._states: dict[str, _EndpointState] = {}

    def get_endpoint_order(self, endpoints: list[str], *, service: str) -> list[str]:
        """Return endpoints sorted by health, excluding currently cooled endpoints.

        If every endpoint is in cooldown, return a single probe endpoint (the one
        that will recover the soonest) to avoid total deadlock.
        """
        unique_endpoints = [ep for ep in dict.fromkeys(endpoints) if ep]
        if not unique_endpoints:
            return []

        now = self._now_fn()
        with self._lock:
            available = []
            cooling = []

            for endpoint in unique_endpoints:
                state = self._states.setdefault(endpoint, _EndpointState())
                if state.cooldown_until_ts > now:
                    cooling.append((endpoint, state))
                else:
                    available.append((endpoint, state))

            if available:
                available.sort(key=lambda item: self._score(item[1]), reverse=True)
                return [ep for ep, _state in available]

            cooling.sort(key=lambda item: item[1].cooldown_until_ts)
            probe_endpoint = cooling[0][0]
            wait_s = max(0.0, cooling[0][1].cooldown_until_ts - now)
            log.warning(
                f"Overpass {service}: all endpoints cooling down; "
                f"probing {probe_endpoint} (cooldown {wait_s:.1f}s remaining)"
            )
            return [probe_endpoint]

    def record_success(self, endpoint: str, *, latency_s: float | None = None) -> None:
        now = self._now_fn()
        with self._lock:
            state = self._states.setdefault(endpoint, _EndpointState())
            state.successes += 1
            state.success_streak += 1
            state.consecutive_failures = 0
            state.cooldown_until_ts = 0.0
            state.last_failure_reason = ""

            if latency_s is not None and latency_s >= 0:
                if state.avg_latency_s is None:
                    state.avg_latency_s = latency_s
                else:
                    alpha = self.latency_alpha
                    state.avg_latency_s = (alpha * latency_s) + ((1.0 - alpha) * state.avg_latency_s)

    def record_failure(self, endpoint: str, *, reason: str) -> None:
        now = self._now_fn()
        with self._lock:
            state = self._states.setdefault(endpoint, _EndpointState())
            state.failures += 1
            state.success_streak = 0
            state.consecutive_failures += 1
            state.last_failure_reason = reason

            if state.consecutive_failures >= self.failure_threshold:
                level = state.consecutive_failures - self.failure_threshold
                cooldown_s = min(self.max_cooldown_s, self.base_cooldown_s * (self.cooldown_backoff ** level))
                state.cooldown_until_ts = max(state.cooldown_until_ts, now + cooldown_s)

    def get_state_snapshot(self, endpoint: str) -> dict:
        """Testing/debug helper with derived cooldown state."""
        now = self._now_fn()
        with self._lock:
            state = self._states.setdefault(endpoint, _EndpointState())
            return {
                "successes": state.successes,
                "failures": state.failures,
                "consecutive_failures": state.consecutive_failures,
                "success_streak": state.success_streak,
                "avg_latency_s": state.avg_latency_s,
                "is_cooling": state.cooldown_until_ts > now,
                "cooldown_remaining_s": max(0.0, state.cooldown_until_ts - now),
                "last_failure_reason": state.last_failure_reason,
            }

    def _score(self, state: _EndpointState) -> float:
        total = state.successes + state.failures
        reliability = (state.successes / total) if total else 0.75
        score = reliability * 100.0
        if state.avg_latency_s is not None:
            score -= min(state.avg_latency_s, 12.0) * 4.0
        score += min(state.success_streak, 5) * 2.5
        score -= min(state.consecutive_failures, 5) * 8.0
        return score


overpass_health = OverpassEndpointHealth()
