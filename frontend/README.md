# rivenforge frontend

React + Vite + Tauri shell for the future standalone app.

## Development

From repo root, start the Python sidecar:

```powershell
python api_sidecar.py --port 8000
```

In another terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open:

```text
http://localhost:1420
```

The Settings page lets you change the API base URL. By default it uses:

```text
http://127.0.0.1:8000
```

## Build React

```powershell
cd frontend
npm run build
```

## Build Python sidecar for Tauri

```powershell
cd frontend
npm run sidecar:build
```

This produces:

```text
frontend\src-tauri\binaries\rivenforge-api-x86_64-pc-windows-msvc.exe
```

## Build Tauri installer

Rust is required. This machine currently does not have `rustc`/`cargo` on PATH.
After installing Rust:

```powershell
cd frontend
npm run sidecar:build
npm run tauri build
```

The legacy PyQt GUI remains in place until this Tauri shell completes a full
manual-analysis and rolling-session pass.
