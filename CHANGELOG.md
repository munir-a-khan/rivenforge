# Changelog

## 0.1.6

- Added a Windows.Graphics.Capture (WGC) backend that reads the Warframe window even while it is covered, unfocused, or on a second monitor. Selectable via `POST /capture/analyze?backend=wgc` and a "Background capture" toggle on Manual Analyze.
- Added `GET /capture/status` (reports window state + available capture backends) and `POST /capture/input-probe` (non-destructive background-input test — hover only, never a click).
- Established the background-input boundary empirically: Warframe ignores posted input, so background analysis works but automated rolling stays foreground-only. No injection or input drivers used.
- Registered the `Ctrl+Shift+Q` emergency-stop hotkey globally through the Tauri shell so it fires while the game has focus.
- OCR fixes: `Weapon Recoil` alias + inverted Recoil polarity (+recoil is a negative, -recoil is a positive); generalized the `(x# for ...)` decorator strip so `Fire Rate (x2 for Bows)` and similar are parsed instead of dropped.
- Sourced the full 34-stat picker from `GET /stats` (both positive and negative pickers) instead of a trimmed hardcoded list.
- Fixed CORS so the Tauri 2 Windows webview origin (`https://tauri.localhost`) can reach the sidecar.
- Added a headless Linux API container (`Dockerfile`, `docker-compose.yml`, `requirements-api.txt`) for the cross-platform half of the API.
- Added `run-rivenforge.bat` and `run-rivenforge-dev.bat` launchers.

## 0.1.5

- Aligned desktop, API diagnostics, and package metadata for public repository handoff.
- Prepared source tree for GitHub publishing with generated logs, screenshots, binaries, and local tool state ignored.

## 0.1.3

- Switched bundled sidecar to fixed localhost port `47321`.
- Removed stale dynamic API port persistence from bundled mode.
- Added reconnecting event WebSocket handling for sidecar restarts and closed connections.
- Added sidecar log tail plumbing in Tauri for future Settings diagnostics.

## 0.1.2

- Fixed stale API port handling in the Tauri UI.
- Settings reconnect now discovers the bundled sidecar port instead of retrying an old localhost URL.
- Settings actions now surface failures instead of silently doing nothing.

## 0.1.1

- Fixed packaged API OCR crashes caused by running Windows OCR from an active ASGI event loop.
- Added regression coverage for worker-thread analysis execution.

## 0.1.0

- Added React/Tauri desktop shell.
- Added bundled FastAPI sidecar startup.
- Added Windows installer builds.
- Added first-run onboarding.
- Added local diagnostic bundle export.
- Added versioned config migration with backup.
- Added parser, rule engine, OCR pipeline, API, and migration tests.
