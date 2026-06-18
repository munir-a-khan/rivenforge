from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request


def test_sidecar_prints_ready_and_serves_health():
    proc = subprocess.Popen(
        [sys.executable, "api_sidecar.py", "--port", "0", "--log-level", "error"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        deadline = time.monotonic() + 10
        ready = ""
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if line.startswith("RIVENFORGE_API_READY "):
                ready = line
                break
        assert ready, "sidecar did not print READY line"

        payload = json.loads(ready.split(" ", 1)[1])
        url = f"http://{payload['host']}:{payload['port']}/health"

        last_error: Exception | None = None
        for _ in range(25):
            try:
                with urllib.request.urlopen(url, timeout=1) as response:
                    body = json.loads(response.read().decode("utf-8"))
                assert body["ready"] is True
                return
            except Exception as e:
                last_error = e
                time.sleep(0.2)
        raise AssertionError(f"sidecar health check failed: {last_error}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
