"""
Standalone FastAPI sidecar entry point.

Binds to a **fixed** localhost port (47321) by default so the React frontend
can hardcode its base URL and never deal with stale-port chaos from past
launches. Pass ``--port 0`` to override and request an OS-picked free port
(useful in CI / parallel test runs).

If the fixed port is already bound by another rivenforge-api process, the
sidecar exits with code 0 immediately — Tauri treats that as "an existing
sidecar is already serving the port, keep using it." Real bind failures
(permission, address-in-use by some unrelated app) exit with code 2.

Always prints a single READY line right before uvicorn starts, so a parent
process can synchronously detect readiness:

    RIVENFORGE_API_READY {"host":"127.0.0.1","port":47321}
"""

from __future__ import annotations

import argparse
import errno
import json
import socket
import sys

import uvicorn

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 47321


def _free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


def _port_is_taken(host: str, port: int) -> bool:
    """True iff someone is currently listening on (host, port)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect((host, port))
        except OSError:
            return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the rivenforge local API sidecar.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"TCP port (default {DEFAULT_PORT}; pass 0 for an OS-picked free port)",
    )
    parser.add_argument("--log-level", default="warning")
    args = parser.parse_args(argv)

    if args.port == 0:
        port = _free_port(args.host)
    else:
        port = args.port
        # Singleton check: if the fixed port is already bound, assume it's
        # an existing rivenforge-api from a prior launch. Print the ready
        # line anyway so the parent learns the port, then exit clean.
        if _port_is_taken(args.host, port):
            print(
                "RIVENFORGE_API_READY "
                + json.dumps(
                    {"host": args.host, "port": port, "reused": True},
                    separators=(",", ":"),
                ),
                flush=True,
            )
            return 0

    print(
        "RIVENFORGE_API_READY "
        + json.dumps({"host": args.host, "port": port}, separators=(",", ":")),
        flush=True,
    )

    try:
        uvicorn.run(
            "api.app:app",
            host=args.host,
            port=port,
            log_level=args.log_level,
            access_log=False,
        )
    except OSError as e:
        if e.errno in (errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", 10048)):
            # Lost a singleton race — another sidecar grabbed the port between
            # our check and uvicorn.bind. Treat as "reused".
            return 0
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
