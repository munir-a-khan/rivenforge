# Packaging

This repo currently has two executable targets:

1. `WFRivenRoller` - the legacy PyQt desktop app (`build.spec`).
2. `rivenforge` - the React/Tauri desktop app with bundled `rivenforge-api`.

## Tauri App

Build the Python sidecar and copy it into Tauri's expected binary folder:

```powershell
cd frontend
npm run sidecar:build
```

Build installers:

```powershell
npm run tauri build
```

Outputs:

```text
frontend\src-tauri\target\release\rivenforge.exe
frontend\src-tauri\target\release\bundle\nsis\rivenforge_*_x64-setup.exe
frontend\src-tauri\target\release\bundle\msi\rivenforge_*_x64_en-US.msi
```

Smoke-test the release exe:

```powershell
frontend\src-tauri\target\release\rivenforge.exe
```

Expected behavior:

- The app window opens without a dev server.
- `rivenforge-api.exe` starts automatically beside the app.
- Settings can export `rivenforge-diagnostics.zip`.
- Manual Analyze accepts a file or pasted image.

## API Sidecar Internals

The sidecar listens on a **fixed port** (`127.0.0.1:47321`) by default, so
the React frontend can hardcode its base URL and never deal with stale-port
chaos from previous runs.

Run the sidecar manually:

```powershell
python api_sidecar.py                  # binds 127.0.0.1:47321
python api_sidecar.py --port 0         # OS-picked free port (CI / parallel tests)
python api_sidecar.py --port 9000      # explicit override
```

The process prints one machine-readable line right before uvicorn binds:

```text
RIVENFORGE_API_READY {"host":"127.0.0.1","port":47321}
```

### Singleton behavior

If `--port` points at an already-bound port (an existing rivenforge-api
left over from a prior launch), the new process:

1. Prints `RIVENFORGE_API_READY {"host":"127.0.0.1","port":47321,"reused":true}`.
2. Exits with code `0` — does **not** error out.

This is what lets the Tauri shell detect an orphan sidecar at startup and
reuse it instead of fighting over the port. The Rust side also probes
`/health` on 47321 before spawning, so duplicate sidecars never happen in
the normal happy path.

Tauri spawns the sidecar, reads the ready line from stdout, then calls:

```text
http://127.0.0.1:47321/health
```

Build the sidecar:

```powershell
python -m pip install -r requirements.txt
pyinstaller api_sidecar.spec
```

Output:

```text
dist\rivenforge-api.exe
```

The sidecar binds to `127.0.0.1` only. Use `--port 0` for an OS-selected free
port, or pass a fixed port during manual testing.

The Tauri build expects the sidecar at:

```text
frontend\src-tauri\binaries\rivenforge-api-x86_64-pc-windows-msvc.exe
```

## Release Checklist

- Run `python -m pytest -q`.
- Run `python -m ruff check .`.
- Run `python -m mypy --follow-imports=skip api core tests`.
- Run `cd frontend; npm run build`.
- Run `cd frontend; npm run sidecar:build`.
- Run `cd frontend; npm run tauri build`.
- Launch the release exe with no dev server running.
- Confirm the bundled API reports online.
- Export diagnostics and verify the zip opens.
- Test Manual Analyze with one saved screenshot and one pasted clipboard image.
- Confirm the app makes no outbound upload of screenshots or diagnostics.

## Legacy PyQt App

Run in development:

```powershell
python main.py
```

Build:

```powershell
pyinstaller build.spec
```

The PyQt target remains available until the Tauri shell has completed an
end-to-end rolling session.
