from __future__ import annotations

import io
import json
import platform
import sys
import zipfile
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from data_util import CONFIG_PATH, CURRENT_CONFIG_SCHEMA_VERSION, load_config

APP_VERSION = "0.1.5"
ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"


def _dependency_versions() -> dict[str, str]:
    packages = [
        "fastapi",
        "uvicorn",
        "pydantic",
        "mss",
        "opencv-python",
        "Pillow",
        "numpy",
        "easyocr",
        "chromadb",
        "sentence-transformers",
    ]
    versions: dict[str, str] = {}
    for package in packages:
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = "not installed"
    return versions


def _config_summary() -> dict[str, Any]:
    cfg = load_config()
    return {
        "schema_version": cfg.get("schema_version", CURRENT_CONFIG_SCHEMA_VERSION),
        "weapon": cfg.get("weapon", ""),
        "weapon_type": cfg.get("weapon_type", ""),
        "profile_count": len(cfg.get("profiles", [])),
        "roll_limit": cfg.get("roll_limit"),
        "rag_threshold": cfg.get("rag_threshold"),
        "animation_wait": cfg.get("animation_wait"),
        "has_button_coords": bool(cfg.get("button_coords")),
        "config_path": CONFIG_PATH,
    }


def _recent_text(path: Path, max_bytes: int = 32_000) -> str:
    data = path.read_bytes()
    return data[-max_bytes:].decode("utf-8", errors="replace")


def build_diagnostic_bundle() -> bytes:
    generated_at = datetime.now(UTC).isoformat()
    manifest = {
        "app": {
            "name": "rivenforge",
            "version": APP_VERSION,
            "generated_at": generated_at,
            "python": sys.version,
            "executable": sys.executable,
        },
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "dependencies": _dependency_versions(),
        "config": _config_summary(),
        "privacy": {
            "network_upload": False,
            "screenshots_included": False,
            "notes": "This bundle is generated locally and is only shared if the user exports it.",
        },
    }

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("config-summary.json", json.dumps(manifest["config"], indent=2))

        if LOG_DIR.exists():
            for log_path in sorted(LOG_DIR.glob("*.log")):
                try:
                    zf.writestr(f"logs/{log_path.name}", _recent_text(log_path))
                except OSError:
                    continue

    return output.getvalue()
