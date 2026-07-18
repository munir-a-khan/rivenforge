"""
Offline license-key verification (Ed25519, zero-server, $0 to run).

A license key is a signed token:

    RVNF1.<b64url(payload_json)>.<b64url(signature)>

The payload is small JSON — ``{"id": "...", "exp": <unix|null>, "tier": "full",
"iss": <unix>}``. It is signed with a private key that only the project owner
holds (``tools/make_license.py``); the app ships ONLY the public key below and
verifies signatures completely offline. Without the private key a key cannot be
forged, so only keys the owner hands out will activate — no license server, no
per-user hosting cost, no network dependency.

The activated key is stored beside the durable user config so it survives
restarts and reinstalls. Verification is cheap (once per launch / on demand).
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass

# Ed25519 PUBLIC key (base64, 32 raw bytes). Safe to embed — it can only verify.
# The matching private key lives in tools/license_private_key.pem (gitignored)
# and is used exclusively by tools/make_license.py to issue keys.
_PUBLIC_KEY_B64 = "8chEM0e3VufRuGZBXrCXmXvcplLAf+AnCw8C2ROkfRg="

_KEY_PREFIX = "RVNF1"


def _license_path() -> str:
    # Store next to the durable user config (see data_util._resolve_config_path).
    from data_util import CONFIG_PATH
    return os.path.join(os.path.dirname(CONFIG_PATH), "license.key")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


@dataclass(frozen=True)
class LicenseInfo:
    licensed: bool
    licensee: str = ""
    tier: str = "full"
    expires: int | None = None      # unix seconds, or None for perpetual
    reason: str = ""                # why unlicensed / any note

    def to_dict(self) -> dict:
        return {
            "licensed": self.licensed,
            "licensee": self.licensee,
            "tier": self.tier,
            "expires": self.expires,
            "reason": self.reason,
        }


def _verify_key_string(key: str) -> LicenseInfo:
    """Verify a key's signature + expiry WITHOUT touching disk."""
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except Exception:
        # Crypto lib missing (shouldn't happen in a real build) — fail closed.
        return LicenseInfo(False, reason="License verification unavailable on this build.")

    parts = (key or "").strip().split(".")
    if len(parts) != 3 or parts[0] != _KEY_PREFIX:
        return LicenseInfo(False, reason="Malformed license key.")

    _, payload_b64, sig_b64 = parts
    try:
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(_PUBLIC_KEY_B64))
        pub.verify(_b64url_decode(sig_b64), payload_b64.encode("ascii"))
    except InvalidSignature:
        return LicenseInfo(False, reason="Invalid license key (signature mismatch).")
    except Exception:
        return LicenseInfo(False, reason="Invalid license key.")

    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception:
        return LicenseInfo(False, reason="Invalid license payload.")

    exp = payload.get("exp")
    if exp is not None and time.time() > float(exp):
        return LicenseInfo(
            False, licensee=str(payload.get("id", "")), expires=int(exp),
            reason="License key has expired.",
        )

    return LicenseInfo(
        licensed=True,
        licensee=str(payload.get("id", "")),
        tier=str(payload.get("tier", "full")),
        expires=int(exp) if exp is not None else None,
    )


def status() -> LicenseInfo:
    """Current license state from the stored key (verified fresh each call)."""
    path = _license_path()
    if not os.path.exists(path):
        return LicenseInfo(False, reason="No license key activated.")
    try:
        with open(path, encoding="utf-8") as f:
            key = f.read().strip()
    except Exception:
        return LicenseInfo(False, reason="Could not read stored license.")
    return _verify_key_string(key)


def activate(key: str) -> LicenseInfo:
    """Verify a key and, if valid, persist it. Returns the resulting status."""
    info = _verify_key_string(key)
    if not info.licensed:
        return info
    path = _license_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(key.strip())
    except Exception:
        return LicenseInfo(False, licensee=info.licensee, reason="Could not save license file.")
    return info


def deactivate() -> None:
    """Remove the stored license (returns silently if none)."""
    try:
        os.remove(_license_path())
    except FileNotFoundError:
        pass
    except Exception:
        pass


def is_licensed() -> bool:
    return status().licensed
