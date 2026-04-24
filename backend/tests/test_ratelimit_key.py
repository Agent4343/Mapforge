"""Tests for the XFF-aware rate-limit key function."""

from types import SimpleNamespace

from app.services.ratelimit import client_ip_key_func


def _req(headers: dict, host: str = "10.0.0.1"):
    """Minimal stand-in for a Starlette Request."""
    return SimpleNamespace(
        headers=headers,
        client=SimpleNamespace(host=host),
    )


def test_xff_first_entry_wins():
    req = _req({"x-forwarded-for": "1.2.3.4, 10.0.0.1, 10.0.0.2"})
    assert client_ip_key_func(req) == "1.2.3.4"


def test_xff_single_entry():
    req = _req({"x-forwarded-for": "5.6.7.8"})
    assert client_ip_key_func(req) == "5.6.7.8"


def test_xff_with_whitespace():
    req = _req({"x-forwarded-for": "   9.9.9.9   , 10.0.0.1"})
    assert client_ip_key_func(req) == "9.9.9.9"


def test_fallback_to_client_host_without_xff():
    req = _req({}, host="127.0.0.1")
    assert client_ip_key_func(req) == "127.0.0.1"


def test_empty_xff_falls_back():
    req = _req({"x-forwarded-for": ""}, host="172.16.0.5")
    assert client_ip_key_func(req) == "172.16.0.5"
