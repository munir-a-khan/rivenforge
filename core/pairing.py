"""
Phone-pairing token (bearer secret for the Android companion).

This is DELIBERATELY separate from the license key:

- The license key (core.license) authorizes *the app itself* to automate. It
  must never be sent to the phone — doing so would leak the thing that gates
  automation.
- The pairing token authorizes *one caller* (the user's phone) to reach the
  sidecar once it is exposed beyond ``127.0.0.1``. It is a random secret with
  no meaning; rotating or clearing it instantly cuts the phone off.

The token is stored beside the durable user config so it survives restarts.
The desktop mints it, shows it as a QR code, and the phone stores it in the
Android Keystore and sends it as ``Authorization: Bearer <token>`` (or a
``?token=`` query param on the WebSocket, which cannot carry headers in every
client).

Security model: the sidecar binds ``127.0.0.1`` by default (no exposure). Only
when phone access is explicitly enabled does it bind ``0.0.0.0`` — and then the
auth guard requires a valid token for every non-loopback request, failing
CLOSED when no token has been generated. Loopback (the desktop UI, tests) is
always exempt, so nothing local changes.
"""

from __future__ import annotations

import hmac
import os
import secrets


def _token_path() -> str:
    # Store next to the durable user config (see data_util._resolve_config_path).
    from data_util import CONFIG_PATH
    return os.path.join(os.path.dirname(CONFIG_PATH), "pair.token")


def get_token() -> str | None:
    """The current pairing token, or None if phone access was never enabled."""
    path = _token_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            token = f.read().strip()
        return token or None
    except Exception:
        return None


def is_paired() -> bool:
    return get_token() is not None


def rotate() -> str:
    """Mint a NEW token (invalidating any old one) and persist it."""
    token = secrets.token_urlsafe(32)
    path = _token_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(token)
    return token


def ensure_token() -> str:
    """Return the existing token, generating one on first use."""
    return get_token() or rotate()


def clear() -> None:
    """Remove the token — immediately disables phone access."""
    try:
        os.remove(_token_path())
    except FileNotFoundError:
        pass
    except Exception:
        pass


def verify(token: str) -> bool:
    """Constant-time check of a presented token against the stored one."""
    stored = get_token()
    if not stored or not token:
        return False
    return hmac.compare_digest(stored, token)
