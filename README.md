# rivenforge

Windows-first riven analysis app for Warframe. The current app is a Tauri desktop shell with a bundled local FastAPI sidecar. Core parsing, rules, config, and tests are Python modules that can run without the game open.

## Current Status

- Manual screenshot analysis works through the React/Tauri UI.
- The rule engine decides from structured riven data only.
- Low-confidence or partial OCR returns `REVIEW`, not `ROLL`.
- The packaged app starts `rivenforge-api.exe` automatically on `127.0.0.1`.
- Legacy PyQt code remains available until the Tauri app completes full feature parity.

## Run From Source

```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
cd frontend
npm install
npm run sidecar:build
npm run tauri dev
```

## Build Windows Installers

Install Rust and Visual Studio C++ Build Tools, then:

```powershell
python -m pytest -q
cd frontend
npm run build
npm run sidecar:build
npm run tauri build
```

Outputs:

- `frontend/src-tauri/target/release/rivenforge.exe`
- `frontend/src-tauri/target/release/bundle/nsis/rivenforge_*_x64-setup.exe`
- `frontend/src-tauri/target/release/bundle/msi/rivenforge_*_x64_en-US.msi`

## Safety Boundaries

rivenforge does not use memory reading, game injection, packet inspection, stealth behavior, kernel drivers, or anti-detection bypasses. Screenshots and diagnostic bundles stay local unless the user exports and shares them.

## License

No open-source license has been selected yet. All rights are reserved unless a license is added later.

## Tests

```powershell
python -m pytest -q
python -m ruff check api core tests data_util.py
python -m mypy --follow-imports=skip api tests/test_api.py tests/test_config_migration.py data_util.py
cd frontend
npm run build
```
