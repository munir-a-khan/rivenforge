from __future__ import annotations

import io
import threading
import zipfile

from fastapi.testclient import TestClient
from PIL import Image

from api.app import app


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (640, 480), color=(0, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


def test_health_endpoint():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["ready"] is True
    assert response.json()["capture_path"] == "mss"


def test_diagnostics_export_returns_zip_manifest():
    client = TestClient(app)

    response = client.get("/diagnostics/export")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        assert "manifest.json" in zf.namelist()
        manifest = zf.read("manifest.json").decode("utf-8")
    assert '"name": "rivenforge"' in manifest


def test_analyze_endpoint_with_manual_ocr_returns_structured_decision():
    client = TestClient(app)

    response = client.post(
        "/analyze",
        files={"screenshot": ("roll.png", _png_bytes(), "image/png")},
        data={
            "crop_mode": "full",
            "manual_ocr_text": "+100% Critical Chance\n+80% Critical Damage\n-30% Impact",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["parse"]["status"] == "ok"
    assert payload["parse"]["positives"][0]["stat"] == "Critical Chance"
    assert payload["decision"]["decision"] in {"KEEP", "ROLL", "REVIEW"}
    assert payload["confidence"] == 1.0


def test_analyze_endpoint_runs_pipeline_off_event_loop_thread(monkeypatch):
    client = TestClient(app)
    caller_thread = threading.get_ident()
    worker_threads: list[int] = []

    def fake_analyze_screenshot(*_args, **_kwargs):
        worker_threads.append(threading.get_ident())
        from core.ocr_pipeline import ScreenshotSource, StaticTextOcrEngine, run_ocr_pipeline

        return run_ocr_pipeline(
            ScreenshotSource(_args[0]),
            crop_mode="full",
            ocr_engine=StaticTextOcrEngine((
                "+100% Critical Chance",
                "+80% Critical Damage",
                "-30% Impact",
            )),
            preprocess=False,
        )

    monkeypatch.setattr("api.app.analyze_screenshot", fake_analyze_screenshot)

    response = client.post(
        "/analyze",
        files={"screenshot": ("roll.png", _png_bytes(), "image/png")},
        data={"crop_mode": "full", "manual_ocr_text": ""},
    )

    assert response.status_code == 200
    assert worker_threads
    assert worker_threads[0] != caller_thread


def test_weapons_endpoint_filters_by_type(monkeypatch):
    def fake_all_weapons():
        return [
            {"weapon": "A", "weapon_type": "melee", "positives": [], "negatives": []},
            {"weapon": "B", "weapon_type": "primary", "positives": [], "negatives": []},
        ]

    monkeypatch.setattr("api.app.all_weapons", fake_all_weapons)
    client = TestClient(app)

    response = client.get("/weapons?type=melee")

    assert response.status_code == 200
    assert response.json() == [{"weapon": "A", "weapon_type": "melee", "positives": [], "negatives": []}]


def test_suggested_profiles_endpoint(monkeypatch):
    monkeypatch.setattr(
        "api.app.weapon_lookup",
        lambda name: [{
            "weapon": name,
            "weapon_type": "melee",
            "positives": ["Critical Damage", "Range"],
            "negatives": ["Impact"],
        }],
    )
    client = TestClient(app)

    response = client.get("/weapons/Nepheri/suggested")

    assert response.status_code == 200
    assert response.json()[0]["desired_positives"] == ["Critical Damage", "Range"]


def test_roll_start_and_stop_are_wrapped(monkeypatch):
    monkeypatch.setattr("api.app.session_manager.start", lambda payload: "session-1")
    monkeypatch.setattr("api.app.session_manager.stop", lambda: True)
    client = TestClient(app)

    start = client.post(
        "/roll/start",
        json={
            "weapon": "Nepheri",
            "weapon_type": "melee",
            "profiles": [],
            "roll_limit": 1,
            "rag_threshold": 0.0,
            "animation_wait": 1.0,
        },
    )
    stop = client.post("/roll/stop")

    assert start.status_code == 200
    assert start.json() == {"session_id": "session-1"}
    assert stop.status_code == 200
    assert stop.json() == {"stopped": True}


def test_shutdown_stops_session_and_schedules_exit(monkeypatch):
    called = {"stop": False, "exit": False}

    def fake_stop():
        called["stop"] = True
        return True

    def fake_exit_later():
        called["exit"] = True

    monkeypatch.setattr("api.app.session_manager.stop", fake_stop)
    monkeypatch.setattr("api.app._exit_process_later", fake_exit_later)
    client = TestClient(app)

    response = client.post("/shutdown")

    assert response.status_code == 200
    assert response.json() == {"shutting_down": True}
    assert called == {"stop": True, "exit": True}
