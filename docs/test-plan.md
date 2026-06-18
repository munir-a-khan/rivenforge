# Test Plan

## One-Command Core Check

```powershell
python -m pytest -q
```

## Static Analysis

```powershell
python -m ruff check api core tests data_util.py
python -m mypy --follow-imports=skip api tests/test_api.py tests/test_config_migration.py data_util.py
```

## Frontend

```powershell
cd frontend
npm run build
```

## Packaging Smoke Test

```powershell
cd frontend
npm run sidecar:build
npm run tauri build
```

Then launch `frontend/src-tauri/target/release/rivenforge.exe` with no dev server running and confirm the bundled API comes online.
