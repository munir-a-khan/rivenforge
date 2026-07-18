"""License verification + the /roll/start gate it protects."""

from __future__ import annotations

import base64
import json
import time

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from core import license as lic

cryptography = pytest.importorskip("cryptography")


@pytest.fixture()
def signing_key():
    """A throwaway keypair whose public half replaces the shipped one."""
    from cryptography.hazmat.primitives import serialization as s
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    priv = Ed25519PrivateKey.generate()
    pub_raw = priv.public_key().public_bytes(s.Encoding.Raw, s.PublicFormat.Raw)
    return priv, base64.b64encode(pub_raw).decode()


@pytest.fixture()
def licensing(tmp_path, monkeypatch, signing_key):
    """Point license storage at tmp_path and trust the test keypair."""
    priv, pub_b64 = signing_key
    monkeypatch.setattr(lic, "_PUBLIC_KEY_B64", pub_b64)
    monkeypatch.setattr(lic, "_license_path", lambda: str(tmp_path / "license.key"))

    def make_key(licensee: str = "Tester", exp: int | None = None) -> str:
        payload = {"id": licensee, "iss": int(time.time()), "tier": "full", "exp": exp}
        blob = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        payload_b64 = base64.urlsafe_b64encode(blob).rstrip(b"=").decode()
        sig = priv.sign(payload_b64.encode("ascii"))
        sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
        return f"RVNF1.{payload_b64}.{sig_b64}"

    return make_key


def test_no_key_is_unlicensed(licensing):
    info = lic.status()
    assert info.licensed is False
    assert "No license" in info.reason


def test_valid_key_activates_and_persists(licensing):
    info = lic.activate(licensing("Alice"))
    assert info.licensed is True
    assert info.licensee == "Alice"
    # Fresh read from disk — survives a "restart".
    assert lic.status().licensed is True
    assert lic.is_licensed() is True


def test_deactivate_clears_license(licensing):
    lic.activate(licensing("Alice"))
    lic.deactivate()
    assert lic.is_licensed() is False
    lic.deactivate()  # idempotent, no raise


def test_expired_key_rejected(licensing):
    info = lic.activate(licensing("Bob", exp=int(time.time()) - 60))
    assert info.licensed is False
    assert "expired" in info.reason.lower()
    assert lic.is_licensed() is False


def test_key_signed_by_another_keypair_rejected(licensing):
    """A key forged without the owner's private key must not verify."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    attacker = Ed25519PrivateKey.generate()
    payload = {"id": "Mallory", "iss": int(time.time()), "tier": "full", "exp": None}
    blob = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    payload_b64 = base64.urlsafe_b64encode(blob).rstrip(b"=").decode()
    sig_b64 = base64.urlsafe_b64encode(attacker.sign(payload_b64.encode())).rstrip(b"=").decode()

    info = lic.activate(f"RVNF1.{payload_b64}.{sig_b64}")
    assert info.licensed is False
    assert lic.is_licensed() is False


def test_tampered_payload_rejected(licensing):
    """Editing the payload of a real key breaks the signature."""
    key = licensing("Alice")
    _, payload_b64, sig_b64 = key.split(".")
    payload = json.loads(lic._b64url_decode(payload_b64))
    payload["id"] = "Mallory"
    blob = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    forged = base64.urlsafe_b64encode(blob).rstrip(b"=").decode()

    assert lic.activate(f"RVNF1.{forged}.{sig_b64}").licensed is False


@pytest.mark.parametrize("bad", ["", "garbage", "RVNF1.only-two", "NOPE1.a.b", "a.b.c"])
def test_malformed_keys_rejected(licensing, bad):
    assert lic.activate(bad).licensed is False


def test_roll_start_gated_when_unlicensed(licensing):
    client = TestClient(create_app())
    resp = client.post("/roll/start", json={"weapon": "Kuva Bramma", "weapon_type": "primary"})
    assert resp.status_code == 402
    assert "license" in resp.json()["detail"].lower()


def test_license_endpoints_roundtrip(licensing):
    client = TestClient(create_app())
    assert client.get("/license/status").json()["licensed"] is False

    activated = client.post("/license/activate", json={"key": licensing("Carol")}).json()
    assert activated["licensed"] is True
    assert activated["licensee"] == "Carol"
    assert client.get("/license/status").json()["licensed"] is True

    assert client.post("/license/deactivate").json()["licensed"] is False


def test_manual_analysis_stays_free_when_unlicensed(licensing):
    """The gate covers automation only — free surfaces must still answer."""
    client = TestClient(create_app())
    assert client.get("/health").status_code == 200
    assert client.get("/config").status_code == 200
    assert client.get("/stats").status_code == 200
