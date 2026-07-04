"""
Tests for the background capture (WGC) + background input (PostMessage)
feature. These are unit-level and platform-tolerant: they must pass in CI
(no Warframe, possibly no pywin32/WGC) as well as on a dev box.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import app
from core import bg_input, capture_wgc

# ── bg_input primitives ──────────────────────────────────────────────────

def test_lparam_packs_client_coords():
    # low word = x, high word = y
    assert bg_input._lparam(10, 20) == ((20 << 16) | 10)
    assert bg_input._lparam(0, 0) == 0
    # values are masked to 16 bits so a stray large coord can't corrupt the word
    assert bg_input._lparam(0x1FFFF, 0) == 0xFFFF


def test_probe_target_with_no_hwnd_is_safe():
    result = bg_input.probe_target(0, 100, 200)
    assert result["posted_move"] is False
    assert result["client_coords"] == [100, 200]
    assert result["notes"]  # explains why nothing was posted


def test_post_helpers_reject_zero_hwnd():
    # No exception, just False — never raise into the roll loop.
    assert bg_input.post_click(0, 5, 5) is False
    assert bg_input.post_mouse_move(0, 5, 5) is False
    assert bg_input.post_key(0, 0x0D) is False


# ── WGC backend ──────────────────────────────────────────────────────────

def test_wgc_capture_invalid_hwnd_returns_none():
    # Whether or not WGC is installed, an invalid hwnd must yield None, not crash.
    assert capture_wgc.capture_window(0) is None


def test_wgc_is_available_is_bool():
    assert isinstance(capture_wgc.is_available(), bool)


# ── capture status + probe endpoints ─────────────────────────────────────

def test_capture_status_reports_backends():
    client = TestClient(app)
    response = client.get("/capture/status")
    assert response.status_code == 200
    body = response.json()
    backends = body["capture_backends"]
    # All three keys always present; values reflect what's installed.
    assert set(backends) == {"mss", "dxcam", "windows_graphics_capture"}
    assert backends["mss"] is True


def test_input_probe_endpoint_returns_structured_result():
    # The probe endpoint must always return a structured 200 — never a 500 —
    # whether or not Warframe is running. Non-destructiveness is guaranteed
    # by the code path itself: the probe only ever posts a MOUSEMOVE (hover),
    # never a button-down/up, so it can't roll a riven or spend kuva.
    client = TestClient(app)
    response = client.post("/capture/input-probe")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["available"], bool)
    assert isinstance(body["posted_move"], bool)
    assert isinstance(body["notes"], list)
