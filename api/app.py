from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from api.diagnostics import build_diagnostic_bundle
from api.events import event_bus
from api.schemas import (
    AnalyzeResponse,
    CropModeStr,
    HealthResponse,
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
from core.ocr_pipeline import StaticTextOcrEngine, analyze_screenshot
from core.profile_schema import load_profile
from core.rules import default_profiles_from_weapon_data
from data_util import load_config, save_config
from rag import rag as rag_mod
from rag.ingest import all_weapons, ingest, weapon_lookup


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

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(ready=True, capture_path="mss")

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
            profiles = []
            for raw in load_config().get("profiles", []):
                try:
                    profiles.append(load_profile(raw))
                except Exception:
                    continue
            analysis = await run_in_threadpool(analyze_pipeline_result, pipeline, profiles)
        finally:
            try:
                temp_path.unlink()
            except OSError:
                pass

        return AnalyzeResponse(
            parse=pipeline.parse.to_legacy(),
            decision=analysis.decision.to_legacy(),
            confidence=pipeline.average_confidence,
            capture_path="mss",
            brightness=0,
            review_reasons=list(pipeline.review_reasons),
        )

    @app.post("/roll/start", response_model=RollStartResponse)
    def roll_start(payload: RollStartRequest) -> RollStartResponse:
        try:
            session_id = session_manager.start(payload.model_dump())
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        return RollStartResponse(session_id=session_id)

    @app.post("/roll/stop", response_model=RollStopResponse)
    def roll_stop() -> RollStopResponse:
        return RollStopResponse(stopped=session_manager.stop())

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
