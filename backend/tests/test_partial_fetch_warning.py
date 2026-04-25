"""Tests for `_warn_on_partial_fetch` — converts MapTiler tile-failure
counts into user-visible warnings on the /generate response."""

from app.routers.generate import _warn_on_partial_fetch


def test_no_warning_when_no_failures():
    warnings = []
    _warn_on_partial_fetch(warnings, "streets", {"tiles_total": 100, "tiles_failed": 0})
    assert warnings == []


def test_no_warning_below_threshold():
    # One failed tile out of 100 = 1%, well under the 10% warn threshold.
    warnings = []
    _warn_on_partial_fetch(warnings, "streets", {"tiles_total": 100, "tiles_failed": 1})
    assert warnings == []


def test_warning_at_threshold():
    warnings = []
    _warn_on_partial_fetch(warnings, "streets", {"tiles_total": 100, "tiles_failed": 10})
    assert len(warnings) == 1
    assert "10%" in warnings[0]
    assert "Streets" in warnings[0]


def test_warning_above_threshold():
    warnings = []
    _warn_on_partial_fetch(warnings, "water", {"tiles_total": 50, "tiles_failed": 20})
    assert len(warnings) == 1
    assert "40%" in warnings[0]
    assert "Water" in warnings[0]


def test_handles_missing_keys():
    """A dict without tile counts (e.g. Overpass fallback) must not warn."""
    warnings = []
    _warn_on_partial_fetch(warnings, "streets", {"major_roads": [], "minor_roads": []})
    assert warnings == []


def test_handles_zero_total():
    """A zero-total edge case (empty bbox) must not divide-by-zero."""
    warnings = []
    _warn_on_partial_fetch(warnings, "streets", {"tiles_total": 0, "tiles_failed": 0})
    assert warnings == []
