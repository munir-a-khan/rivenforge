# Changelog

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
