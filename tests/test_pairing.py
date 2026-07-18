"""
Phone-pairing token + the network auth gate it protects.

The sidecar is loopback-only by default; when exposed to the LAN for the phone
companion, every non-loopback request must carry a valid pairing token.

TestClient always presents host "testclient", so to exercise the *remote* path
we patch api.app._LOCAL_HOSTS to exclude it — then the same client is treated
as a LAN phone.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api.app as app_mod
from api.app import create_app
from core import pairing


@pytest.fixture()
def paired(tmp_path, monkeypatch):
    """Point token storage at tmp_path so tests don't touch real config."""
    monkeypatch.setattr(pairing, "_token_path", lambda: str(tmp_path / "pair.token"))
    return pairing


def _as_remote(monkeypatch):
    """Make TestClient's host ("testclient") look like a LAN phone."""
    monkeypatch.setattr(app_mod, "_LOCAL_HOSTS", {"127.0.0.1", "::1", "localhost"})
    return TestClient(create_app())


# ── pairing token unit behavior ──────────────────────────────────────────────

def test_starts_unpaired(paired):
    assert paired.get_token() is None
    assert paired.is_paired() is False
    assert paired.verify("anything") is False


def test_rotate_mints_and_persists(paired):
    t = paired.rotate()
    assert t and paired.is_paired()
    assert paired.get_token() == t          # survives a re-read ("restart")
    assert paired.verify(t) is True
    assert paired.verify(t + "x") is False


def test_rotate_invalidates_old_token(paired):
    old = paired.rotate()
    new = paired.rotate()
    assert old != new
    assert paired.verify(old) is False
    assert paired.verify(new) is True


def test_clear_disables(paired):
    paired.rotate()
    paired.clear()
    assert paired.is_paired() is False
    paired.clear()  # idempotent


# ── the HTTP auth gate ───────────────────────────────────────────────────────

def test_local_requests_never_need_a_token(paired):
    client = TestClient(create_app())  # host == "testclient" → local
    assert client.get("/config").status_code == 200
    assert client.get("/roll/session").status_code == 200


def test_remote_request_without_token_is_rejected(paired, monkeypatch):
    resp = _as_remote(monkeypatch).get("/config")
    assert resp.status_code == 401
    assert "pair" in resp.json()["detail"].lower()


def test_remote_request_with_valid_token_is_allowed(paired, monkeypatch):
    token = paired.rotate()
    client = _as_remote(monkeypatch)
    assert client.get("/config", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert client.get("/roll/session", params={"token": token}).status_code == 200


def test_remote_request_with_bad_token_is_rejected(paired, monkeypatch):
    paired.rotate()
    client = _as_remote(monkeypatch)
    assert client.get("/config", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_health_is_reachable_before_pairing(paired, monkeypatch):
    # A phone can confirm the PC is up before it has a token.
    assert _as_remote(monkeypatch).get("/health").status_code == 200


def test_remote_cannot_manage_pairing(paired, monkeypatch):
    token = paired.rotate()
    client = _as_remote(monkeypatch)
    assert client.post("/pair/rotate", headers={"Authorization": f"Bearer {token}"}).status_code == 403
    assert client.post("/pair/clear", headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_pair_status_hides_token_from_remote(paired, monkeypatch):
    token = paired.rotate()
    remote = _as_remote(monkeypatch).get("/pair/status", headers={"Authorization": f"Bearer {token}"})
    assert remote.status_code == 200
    body = remote.json()
    assert body["paired"] is True
    assert body["token"] is None      # never echoed to a remote caller
    assert body["lan_ip"] is None


def test_pair_status_shows_token_to_desktop(paired):
    token = paired.rotate()
    body = TestClient(create_app()).get("/pair/status").json()
    assert body["paired"] is True
    assert body["token"] == token      # desktop needs it to render the QR
    assert isinstance(body["lan_ip"], str) and body["lan_ip"]


def test_desktop_can_rotate_and_clear(paired):
    client = TestClient(create_app())
    t = client.post("/pair/rotate").json()["token"]
    assert t and paired.verify(t)
    assert client.post("/pair/clear").json() == {"paired": False}
    assert paired.is_paired() is False


# ── the WebSocket gate ───────────────────────────────────────────────────────

def test_ws_local_connects_without_token(paired):
    with TestClient(create_app()).websocket_connect("/events"):
        pass  # accepted → no exception


def test_ws_remote_without_token_is_closed(paired, monkeypatch):
    from starlette.websockets import WebSocketDisconnect
    client = _as_remote(monkeypatch)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/events"):
            pass


def test_ws_remote_with_token_connects(paired, monkeypatch):
    token = paired.rotate()
    client = _as_remote(monkeypatch)
    with client.websocket_connect(f"/events?token={token}"):
        pass  # accepted
