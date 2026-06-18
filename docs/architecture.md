# Architecture

rivenforge is split into four layers:

- `core/`: domain model, parser, OCR pipeline contracts, rule engine, config/profile schema.
- `api/`: local FastAPI sidecar used by the desktop shell.
- `frontend/`: React/Tauri desktop shell.
- `gui/`: legacy PyQt interface retained during migration.

The GUI does not decide keep/roll directly. It sends screenshots or config to the API. The API runs OCR/parsing and passes structured riven data to the rule engine. Automation remains optional and separate from parsing/rules.

## Decision Flow

1. Screenshot or manual OCR text enters the OCR pipeline.
2. Parser produces structured positives, negatives, confidence, and issues.
3. Analysis returns `KEEP`, `ROLL`, or `REVIEW`.
4. `REVIEW` is mandatory for partial or low-confidence OCR.
5. RAG/market scoring is advisory only and cannot override a failed rule profile.
