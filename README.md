# rivenforge

rivenforge is a Windows-first Warframe riven analysis desktop app. It combines a polished React/Tauri interface, a local FastAPI sidecar, OCR preprocessing, deterministic parsing, profile-based rule matching, and an advisory RAG/market scoring layer.

The goal is reliability first: the app should be useful without touching the game, testable without OCR, and safe enough that bad OCR returns `REVIEW` instead of making a wrong roll decision.

## What It Does

- Analyzes saved riven screenshots or pasted clipboard images.
- Parses riven stat lines into structured positive and negative stats.
- Evaluates rolls against user-defined profiles instead of hardcoded "good roll" guesses.
- Explains why a roll matched, failed, or needs review.
- Uses a local RAG index as extra context for weapon tier/stat suggestions.
- Bundles the Python API as `rivenforge-api.exe` inside the Tauri desktop app.
- Keeps automation optional and separate from OCR, rules, and profile testing.

## Current App

The main app is the Tauri/React desktop shell in `frontend/`. The older PyQt GUI remains in `gui/` until the Tauri version has complete feature parity.

Current React screens:

- Roll Log: session status and roll history.
- Profiles: weapon selection, profile generation, stat preferences, and config save flow.
- Manual Analyze: screenshot upload, clipboard paste, crop mode selection, manual OCR override, parse output, decision, and confidence.
- Settings: API connection, RAG index status/rebuild, safety note, and diagnostic export.

The packaged app starts the sidecar automatically on:

```text
http://127.0.0.1:47321
```

## Figma And UI Direction

The UI was built from a Figma-style direction rather than left as a plain engineering panel. The visual target was a compact desktop tool with a dark violet/magenta Warframe-inspired look, clear navigation, visible status cards, and practical controls that feel like a real Windows app rather than a script wrapper.

That direction became the React/Tauri app:

- A persistent left navigation rail for Roll Log, Profiles, Manual Analyze, and Settings.
- High-contrast status cards for rolls, profiles, accepted/rejected counts, API state, and confidence.
- A manual analysis workflow designed around drag/drop, file selection, and clipboard paste.
- Profile controls that expose stat selection directly instead of hiding the rule system.
- A debug-friendly Settings screen with RAG rebuild and diagnostics export.

The UI is intentionally presentable because this project is also meant to demonstrate product engineering: frontend polish, local app packaging, sidecar integration, safety boundaries, and testing discipline all in one repo.

Screenshots should be added once the next stable build is captured, but the current UI work lives in `frontend/src/App.tsx` and `frontend/src/styles.css`.

## Architecture

```text
React/Tauri UI
    |
    | HTTP + WebSocket on localhost
    v
FastAPI sidecar
    |
    +--> OCR pipeline
    +--> parser
    +--> profile/rule engine
    +--> RAG and market scoring
    +--> diagnostics/config/logging
```

Main folders:

- `frontend/`: React, TypeScript, Tauri shell, sidecar startup, app UI.
- `api/`: FastAPI endpoints used by the desktop shell.
- `core/`: parser, domain model, OCR pipeline, stat registry, rule engine, automation boundaries.
- `rag/`: local tier-list index, TF-IDF retrieval, Warframe.Market price signal helpers.
- `data/`: generated JSON index, stat aliases, template assets.
- `tests/`: parser, rules, OCR pipeline, API, and config migration tests.
- `docs/`: architecture, profile schema, security, troubleshooting, and test plan notes.
- `.github/`: CI, release workflow, and issue templates.

The UI does not decide keep/roll directly. OCR does not decide keep/roll directly. The rule engine receives structured riven data and returns a decision with traces.

## Decision Flow

1. A screenshot or pasted image enters the OCR pipeline.
2. The crop mode selects what part of the screenshot to inspect.
3. OCR text is cleaned and parsed into structured riven stats.
4. Low-confidence, empty, or partial parse results return `REVIEW`.
5. Valid structured stats are checked against saved profiles.
6. The rule engine returns `KEEP`, `ROLL`, or `REVIEW` with an explanation.
7. RAG/market information is shown as advisory context, not as final authority.

This means a random Warframe.Market listing cannot force the app to keep something you did not ask for. Profiles and parse confidence are the guardrails.

## Crop Modes

Manual Analyze supports crop modes because Warframe's riven screen appears in a few different layouts.

- Single card: use when one riven card is centered on screen.
- Full card: use when the full visible card frame and text area need to be preserved for OCR.
- Full screenshot/options: use when comparing old/new roll options or when the card position has shifted after cycling.

The crop choice affects OCR input only. It does not change the rule profile or bypass review behavior.

## Rule Engine

Profiles are versioned JSON-compatible objects. A profile can express:

- required positive stat groups,
- 2 positive + 1 negative style profiles,
- 3 positive + 1 negative style profiles,
- OR groups,
- `Any` slots,
- safe negatives,
- rejected negatives,
- required negatives,
- explanation traces for matches and failures.

Examples of rule behavior:

- If a required positive group is missing, the failure says which group/stat was missing.
- If a rejected negative appears, the profile fails immediately.
- If OCR is partial or low confidence, the result is `REVIEW`, never `ROLL`.
- If no profile is configured, the result is `REVIEW`.

## Built-In RAG

The built-in RAG layer is local and lightweight. It is not a cloud AI service and it does not upload screenshots.

The index is built from a tier-list spreadsheet into:

- `data/riven_index.json`: structured weapon entries with desired positives, acceptable negatives, notes, and weapon type.
- `data/tfidf_model.json`: a pure-Python TF-IDF model for similarity search.

At runtime, RAG combines several advisory signals:

- Tier-list alignment: whether the roll's stats line up with the local weapon entry.
- TF-IDF similarity: whether the current roll resembles indexed tier-list text.
- Warframe.Market price signal: optional live auction context for similar stat combinations.
- Melee fallback logic: local priority rules for cases where market data is sparse.

Important: RAG is context, not control. The deterministic profile/rule engine owns the keep/roll decision. Market data can help explain value, but it should not override your chosen profile.

## API Surface

The local sidecar exposes endpoints such as:

- `GET /health`
- `GET /stats`
- `GET /config`
- `PUT /config`
- `GET /weapons`
- `GET /weapons/{name}/suggested`
- `POST /analyze`
- `POST /roll/start`
- `POST /roll/stop`
- `GET /rag/status`
- `POST /rag/rebuild`
- `GET /diagnostics/export`
- `WS /events`

The sidecar binds to `127.0.0.1` only.

## Run From Source

Install Python dependencies:

```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
```

Install frontend dependencies and run the Tauri app:

```powershell
cd frontend
npm install
npm run sidecar:build
npm run tauri dev
```

Run only the API sidecar:

```powershell
python api_sidecar.py
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

## Tests And Tooling

```powershell
python -m pytest -q
python -m ruff check api core tests data_util.py api_sidecar.py
python -m mypy --follow-imports=skip api tests/test_api.py tests/test_config_migration.py data_util.py api_sidecar.py
cd frontend
npm run build
```

GitHub Actions runs Python tests, Ruff, mypy, frontend build, sidecar packaging, and a Tauri packaging check.

## Safety Boundaries

rivenforge does not use memory reading, game injection, packet manipulation, stealth behavior, anti-detection bypasses, kernel drivers, or hidden background behavior.

Screenshots and diagnostics stay local unless the user explicitly exports and shares them. Automation remains optional; manual screenshot analysis and profile testing work without any in-game clicking.

## Roadmap

- Improve OCR reliability while Warframe is not the focused window.
- Expand fixture-based OCR regression tests.
- Finish Tauri feature parity before removing the PyQt GUI.
- Improve profile import/export and sample profiles.
- Add clearer diagnostics around failed OCR/crop detection.
- Package repeatable Windows releases through GitHub Actions.

## License

No open-source license has been selected yet. All rights are reserved unless a license is added later.
