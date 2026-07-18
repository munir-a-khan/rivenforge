"""
Issue rivenforge license keys (OWNER ONLY).

Requires the private signing key at tools/license_private_key.pem, which is
gitignored and must never be shared or committed. The app ships only the
matching public key (core.license._PUBLIC_KEY_B64) and verifies offline.

Usage:
    python tools/make_license.py "Alice"                 # perpetual key for "Alice"
    python tools/make_license.py "Bob" --days 30         # 30-day key
    python tools/make_license.py --genkeys               # one-time: create a NEW keypair
                                                         # (prints the public key to embed)

Give the printed RVNF1.… string to the person; they paste it into
Settings → License → Activate.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time

PRIV_PATH = os.path.join(os.path.dirname(__file__), "license_private_key.pem")


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def genkeys() -> None:
    from cryptography.hazmat.primitives import serialization as s
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if os.path.exists(PRIV_PATH):
        print(f"Refusing to overwrite existing {PRIV_PATH}", file=sys.stderr)
        sys.exit(1)
    priv = Ed25519PrivateKey.generate()
    pem = priv.private_bytes(s.Encoding.PEM, s.PrivateFormat.PKCS8, s.NoEncryption())
    with open(PRIV_PATH, "wb") as f:
        f.write(pem)
    pub_raw = priv.public_key().public_bytes(s.Encoding.Raw, s.PublicFormat.Raw)
    print("New keypair created.")
    print(f"  private key: {PRIV_PATH} (keep secret, gitignored)")
    print("  EMBED THIS in core/license.py _PUBLIC_KEY_B64:")
    print(f"    {base64.b64encode(pub_raw).decode()}")


def issue(licensee: str, days: int | None) -> str:
    from cryptography.hazmat.primitives import serialization as s

    if not os.path.exists(PRIV_PATH):
        print(f"Missing {PRIV_PATH}. Run: python tools/make_license.py --genkeys", file=sys.stderr)
        sys.exit(1)
    with open(PRIV_PATH, "rb") as f:
        priv = s.load_pem_private_key(f.read(), password=None)

    now = int(time.time())
    payload = {"id": licensee, "iss": now, "tier": "full",
               "exp": (now + days * 86400) if days else None}
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = priv.sign(payload_b64.encode("ascii"))  # type: ignore[union-attr]
    return f"RVNF1.{payload_b64}.{_b64url(sig)}"


def main() -> None:
    ap = argparse.ArgumentParser(description="Issue rivenforge license keys.")
    ap.add_argument("licensee", nargs="?", help="name/id printed inside the key")
    ap.add_argument("--days", type=int, default=None, help="expiry in days (omit = perpetual)")
    ap.add_argument("--genkeys", action="store_true", help="create a new signing keypair")
    args = ap.parse_args()

    if args.genkeys:
        genkeys()
        return
    if not args.licensee:
        ap.error("licensee is required (or pass --genkeys)")

    key = issue(args.licensee, args.days)
    exp = f"{args.days}-day" if args.days else "perpetual"
    print(f"License for {args.licensee!r} ({exp}):\n\n{key}\n")


if __name__ == "__main__":
    main()
