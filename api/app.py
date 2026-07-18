from __future__ import annotations

import os
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from api.diagnostics import build_diagnostic_bundle
from api.events import event_bus
from api.schemas import (
    AnalyzeResponse,
    CaptureBackendStr,
    CaptureStatusResponse,
    CropModeStr,
    HealthResponse,
    InputProbeResponse,
    RagRebuildResponse,
    RagStatusResponse,
    RollStartRequest,
    RollStartResponse,
    RollStopResponse,
    SaveResponse,
    WeaponTypeStr,
)
from api.sessions import session_manager
from core.analysis import analyze_pipeline_result
from core.capture import warframe_window_status
from core.ocr_pipeline import (
    OcrPipelineResult,
    ScreenCaptureSource,
    StaticTextOcrEngine,
    analyze_screenshot,
    run_ocr_pipeline,
)
from core.profile_schema import load_profile
from core.rules import default_profiles_from_weapon_data
from data_util import load_config, save_config
from rag import rag as rag_mod
from rag.ingest import all_weapons, ingest, weapon_lookup

# Hosts treated as "local" (the desktop UI and the test client). Requests from
# any other host — i.e. a phone on the LAN once the sidecar is exposed — must
# carry a valid pairing token. "testclient" keeps Starlette's TestClient local.
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}

# Endpoints reachable without a pairing token even from a remote host, so a
# phone can confirm the PC is reachable before it has paired.
_PAIR_EXEMPT_PATHS = {"/health"}


def _is_local(host: str | None) -> bool:
    return host in _LOCAL_HOSTS


def _bearer_or_query_token(headers: Any, query_token: str) -> str:
    auth = ""
    try:
        auth = headers.get("authorization", "") or ""
    except Exception:
        auth = ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (query_token or "").strip()


def _lan_ip() -> str:
    """
    Best-effort primary LAN IPv4, so the desktop can tell the phone which
    address to reach. Uses a UDP socket to a public IP purely to discover which
    local interface routes outbound — no packet is actually sent.
    """
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return str(s.getsockname()[0])
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"
    finally:
        s.close()


def _exit_process_later(delay_seconds: float = 0.2) -> None:
    def run() -> None:
        time.sleep(delay_seconds)
        os._exit(0)

    threading.Thread(target=run, name="rivenforge-api-shutdown", daemon=True).start()


def _configured_profiles() -> list[Any]:
    profiles = []
    for raw in load_config().get("profiles", []):
        try:
            profiles.append(load_profile(raw))
        except Exception:
            continue
    return profiles


def _run_input_probe() -> InputProbeResponse:
    """
    Post a non-destructive hover to a Warframe UI button and report it.

    Uses WGC to read the (possibly covered) window, the existing vision
    button-finder to locate a target, and bg_input to post a MOUSEMOVE only.
    Never clicks — so it can't roll a riven or spend kuva. This is how the
    user gets an empirical yes/no on whether background input registers.
    """
    from core import bg_input, capture_wgc, vision
    from core.capture import warframe_window_status

    status = warframe_window_status()
    notes: list[str] = []
    hwnd = status.get("hwnd")

    if not bg_input.is_available():
        return InputProbeResponse(available=False, notes=["pywin32 unavailable; cannot post input."])
    if not hwnd:
        return InputProbeResponse(available=True, notes=["Warframe window not found; is the game running?"])
    if status.get("minimized"):
        return InputProbeResponse(
            available=True, hwnd=hwnd,
            notes=["Warframe is minimized — restore it (it can stay unfocused) and retry."],
        )

    frame = capture_wgc.capture_window(int(hwnd)) if capture_wgc.is_available() else None
    backend_used = "wgc" if frame is not None else None
    if frame is None:
        # Fall back to the auto ladder just to locate a button coordinate.
        from core.capture import grab_frame
        frame = grab_frame(backend="auto")
        backend_used = frame.info.get("capture_path", "auto")
        notes.append("WGC frame unavailable; used desktop capture to locate a button.")

    buttons = vision.find_all_buttons(frame)
    target = None
    target_label = None
    for label in ("cycle_button", "confirm_button", "cycle_yes", "keep_yes"):
        pos = buttons.get(label)
        if pos:
            target, target_label = pos, label
            break

    if target is None:
        notes.append(
            "No riven-UI button found on screen. Open the riven cycling screen "
            "in Warframe and retry so the probe has a target to hover."
        )
        return InputProbeResponse(
            available=True, hwnd=hwnd, capture_backend_used=backend_used, notes=notes,
        )

    # Button coords are in captured-frame space, which for a WGC window
    # capture is client space. Post a hover there — no click.
    cx, cy = int(target[0]), int(target[1])
    probe = bg_input.probe_target(int(hwnd), cx, cy)
    notes.extend(probe.get("notes", []))
    return InputProbeResponse(
        available=True,
        hwnd=hwnd,
        posted_move=bool(probe.get("posted_move")),
        client_coords=[cx, cy],
        target_label=target_label,
        capture_backend_used=backend_used,
        notes=notes,
    )


def _analyze_response_from_pipeline(pipeline: OcrPipelineResult, analysis: Any) -> AnalyzeResponse:
    capture_path = pipeline.capture_info.get("capture_path", "mss")
    if capture_path not in {"mss", "dxgi", "mss(dark)", "wgc"}:
        capture_path = "mss"
    return AnalyzeResponse(
        parse=pipeline.parse.to_legacy(),
        decision=analysis.decision.to_legacy(),
        confidence=pipeline.average_confidence,
        capture_path=capture_path,
        brightness=int(pipeline.capture_info.get("brightness", 0)),
        brightness_p95=int(pipeline.capture_info.get("brightness_p95", 0)),
        raw_image_size=pipeline.raw_image_size,
        crop_image_size=pipeline.crop_image_size,
        review_reasons=list(pipeline.review_reasons),
    )


def create_app() -> FastAPI:
    app = FastAPI(title="rivenforge local API", version="0.1.0")
    # CORS allowlist:
    #   - http://localhost:1420 / 127.0.0.1:1420 — Vite dev server
    #   - tauri://localhost                       — Tauri v1 webview (macOS path)
    #   - https://tauri.localhost                 — Tauri v2 webview on Windows
    #   - http://tauri.localhost                  — Tauri v2 webview, fallback
    # The sidecar binds to 127.0.0.1 only, so loosening the list does not
    # expose anything to the network. Adding the v2 Windows origin is the
    # whole reason the React app could not reach /health, /stats, /config
    # while showing "Failed to fetch."
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:1420",
            "http://localhost:1420",
            "tauri://localhost",
            "https://tauri.localhost",
            "http://tauri.localhost",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _pairing_guard(request: Request, call_next):
        # Loopback (desktop UI, tests) is always allowed. A remote caller — a
        # phone reaching the sidecar once it is bound to 0.0.0.0 — must present
        # a valid pairing token. Fails CLOSED: if no token has ever been minted,
        # every remote request is rejected. HTTP only; the WebSocket route does
        # its own check (middleware does not see WS handshakes).
        host = request.client.host if request.client else None
        if not _is_local(host) and request.url.path not in _PAIR_EXEMPT_PATHS:
            from core import pairing
            token = _bearer_or_query_token(request.headers, request.query_params.get("token", ""))
            if not pairing.verify(token):
                return JSONResponse(
                    {"detail": "Pairing required. Scan the code in Settings → Phone Access."},
                    status_code=401,
                )
        return await call_next(request)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(ready=True, capture_path="mss")

    @app.get("/capture/status", response_model=CaptureStatusResponse)
    def capture_status() -> CaptureStatusResponse:
        return CaptureStatusResponse(**warframe_window_status())

    @app.get("/stats")
    def get_stats() -> list[str]:
        """
        Return every canonical riven stat name (sorted), sourced from
        data/stat_aliases.json. The frontend uses this list for BOTH the
        desired-positives and acceptable-negatives pickers — no filtering
        between them — because plenty of niche builds want stats most
        guides would consider "bad" (e.g. -Initial Combo on a non-heavy
        melee, -Damage to Grineer on a Corpus-only build).
        """
        from data.stat_aliases_loader import ALL_STATS
        return list(ALL_STATS)

    @app.get("/diagnostics/export")
    def diagnostics_export() -> Response:
        return Response(
            content=build_diagnostic_bundle(),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="rivenforge-diagnostics.zip"'},
        )

    @app.get("/config")
    def get_config() -> dict[str, Any]:
        return dict(load_config())

    @app.put("/config", response_model=SaveResponse)
    def put_config(cfg: dict[str, Any]) -> SaveResponse:
        save_config(cfg)
        return SaveResponse(saved=True)

    @app.get("/weapons")
    def get_weapons(type: WeaponTypeStr | None = None) -> list[dict[str, Any]]:  # noqa: A002
        weapons = [dict(w) for w in all_weapons()]
        if type is not None:
            weapons = [w for w in weapons if w.get("weapon_type") == type]
        return weapons

    @app.get("/weapons/{name}/suggested")
    def suggested_profiles(name: str) -> list[dict[str, Any]]:
        profiles: list[dict[str, Any]] = []
        for entry in weapon_lookup(name):
            profiles.extend(default_profiles_from_weapon_data(entry))
        return profiles

    @app.post("/analyze", response_model=AnalyzeResponse)
    async def analyze(
        screenshot: Annotated[UploadFile, File()],
        crop_mode: Annotated[CropModeStr, Form()] = "new_card",
        manual_ocr_text: Annotated[str, Form()] = "",
    ) -> AnalyzeResponse:
        suffix = Path(screenshot.filename or "screenshot.png").suffix or ".png"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            f.write(await screenshot.read())
            temp_path = Path(f.name)

        manual_lines = tuple(line.strip() for line in manual_ocr_text.splitlines() if line.strip())
        ocr_engine = StaticTextOcrEngine(manual_lines) if manual_lines else None
        try:
            pipeline = await run_in_threadpool(
                analyze_screenshot,
                temp_path,
                crop_mode=crop_mode,
                ocr_engine=ocr_engine,
            )
            profiles = _configured_profiles()
            analysis = await run_in_threadpool(analyze_pipeline_result, pipeline, profiles)
        finally:
            try:
                temp_path.unlink()
            except OSError:
                pass

        return _analyze_response_from_pipeline(pipeline, analysis)

    @app.post("/capture/analyze", response_model=AnalyzeResponse)
    async def capture_analyze(
        crop_mode: Annotated[CropModeStr, Form()] = "new_card",
        monitor_index: Annotated[int, Form()] = 0,
        backend: Annotated[CaptureBackendStr, Form()] = "auto",
    ) -> AnalyzeResponse:
        # backend="wgc" captures the Warframe window directly (works even
        # when it's covered / unfocused / on a second monitor); "auto" uses
        # the fast mss -> DXGI ladder for the foreground/visible case.
        pipeline = await run_in_threadpool(
            run_ocr_pipeline,
            ScreenCaptureSource(monitor_index=monitor_index, backend=backend),
            crop_mode=crop_mode,
        )
        analysis = await run_in_threadpool(
            analyze_pipeline_result,
            pipeline,
            _configured_profiles(),
        )
        return _analyze_response_from_pipeline(pipeline, analysis)

    @app.post("/capture/input-probe", response_model=InputProbeResponse)
    async def capture_input_probe() -> InputProbeResponse:
        """
        Non-destructive test of whether Warframe honors background
        (PostMessage) input. Captures the window via WGC, finds a UI button,
        posts a HOVER to it (never a click, so no riven is rolled), and
        reports what happened. The user compares the before/after window
        visually to decide whether background rolling is viable.
        """
        return await run_in_threadpool(_run_input_probe)

    @app.get("/license/status")
    def license_status() -> dict[str, Any]:
        from core import license as _lic
        return _lic.status().to_dict()

    @app.post("/license/activate")
    def license_activate(payload: dict[str, Any]) -> dict[str, Any]:
        from core import license as _lic
        info = _lic.activate(str(payload.get("key", "")))
        return info.to_dict()

    @app.post("/license/deactivate")
    def license_deactivate() -> dict[str, Any]:
        from core import license as _lic
        _lic.deactivate()
        return _lic.status().to_dict()

    @app.get("/pair/status")
    def pair_status(request: Request) -> dict[str, Any]:
        # The token + LAN address are returned only to the desktop (loopback):
        # a remote caller that already holds the token doesn't need it echoed,
        # and one that doesn't can't reach here (the guard rejected it).
        from core import pairing
        local = _is_local(request.client.host if request.client else None)
        token = pairing.get_token()
        return {
            "paired": token is not None,
            "enabled": bool(load_config().get("phone_access_enabled")),
            "token": token if local else None,
            "lan_ip": _lan_ip() if local else None,
        }

    @app.post("/pair/rotate")
    def pair_rotate(request: Request) -> dict[str, Any]:
        # Only the desktop owner (loopback) may mint/rotate a token, so a paired
        # phone can't silently re-key access.
        if not _is_local(request.client.host if request.client else None):
            raise HTTPException(status_code=403, detail="Pairing can only be managed from the desktop.")
        from core import pairing
        return {"paired": True, "token": pairing.rotate()}

    @app.post("/pair/clear")
    def pair_clear(request: Request) -> dict[str, bool]:
        if not _is_local(request.client.host if request.client else None):
            raise HTTPException(status_code=403, detail="Pairing can only be managed from the desktop.")
        from core import pairing
        pairing.clear()
        return {"paired": False}

    @app.get("/roll/session")
    def roll_session() -> dict[str, Any]:
        # What is running right now, for a phone joining mid-session (the WS
        # only streams NEW events).
        return session_manager.snapshot()

    @app.post("/roll/start", response_model=RollStartResponse)
    def roll_start(payload: RollStartRequest) -> RollStartResponse:
        # Automated rolling is the licensed feature. Manual analysis stays free.
        from core import license as _lic
        info = _lic.status()
        if not info.licensed:
            raise HTTPException(
                status_code=402,
                detail=(info.reason or "A license key is required.")
                + " Activate a key in Settings → License.",
            )
        try:
            session_id = session_manager.start(payload.model_dump())
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        return RollStartResponse(session_id=session_id)

    @app.post("/roll/stop", response_model=RollStopResponse)
    def roll_stop() -> RollStopResponse:
        return RollStopResponse(stopped=session_manager.stop())

    @app.post("/shutdown")
    def shutdown() -> dict[str, bool]:
        session_manager.stop()
        try:
            from core.automation import release_input_state
            release_input_state()
        except Exception:
            pass
        _exit_process_later()
        return {"shutting_down": True}

    @app.get("/rag/status", response_model=RagStatusResponse)
    def rag_status() -> RagStatusResponse:
        entries = 0
        if rag_mod.is_db_ready():
            try:
                entries = len(all_weapons())
            except Exception:
                entries = 0
        return RagStatusResponse(ready=rag_mod.is_db_ready(), entries=entries)

    @app.post("/rag/rebuild", response_model=RagRebuildResponse)
    def rag_rebuild(background_tasks: BackgroundTasks) -> RagRebuildResponse:
        job_id = str(uuid.uuid4())

        def run() -> None:
            try:
                total = ingest(
                    progress_cb=lambda current, max_total: event_bus.publish_threadsafe({
                        "kind": "ingest",
                        "job_id": job_id,
                        "current": current,
                        "total": max_total,
                    })
                )
                event_bus.publish_threadsafe({"kind": "ingest_done", "job_id": job_id, "total": total})
            except Exception as e:
                event_bus.publish_threadsafe({"kind": "error", "job_id": job_id, "message": str(e)})

        background_tasks.add_task(run)
        return RagRebuildResponse(job_id=job_id)

    @app.websocket("/events")
    async def events(ws: WebSocket) -> None:
        # The live roll stream. Loopback (desktop UI) is open; a remote phone
        # must present a valid pairing token (?token=… or a Bearer header) or
        # the socket is closed with a policy-violation code before accept.
        host = ws.client.host if ws.client else None
        if not _is_local(host):
            from core import pairing
            token = _bearer_or_query_token(ws.headers, ws.query_params.get("token", ""))
            if not pairing.verify(token):
                await ws.close(code=1008)  # policy violation
                return
        await ws.accept()
        try:
            async for event in event_bus.subscribe():
                await ws.send_json(event)
        except (WebSocketDisconnect, ConnectionResetError, ConnectionAbortedError):
            # Client closed the socket. Normal during route navigation /
            # reload — don't let asyncio log a scary "An existing connection
            # was forcibly closed" traceback.
            return
        except Exception:
            # Any other error is best-effort closed; the bus iterator is
            # cooperative so it'll wind down naturally.
            return

    return app


app = create_app()
