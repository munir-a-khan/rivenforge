"""
Load/save user_config.json.

Path resolution matters here — this was the "config resets to the build-time
weapon on every launch" bug:

- **Frozen (PyInstaller sidecar)**: ``__file__`` lives in the ephemeral
  ``_MEIxxxxx`` extraction dir, which is re-created (from the build-time
  snapshot) on every process start and deleted afterwards. Writing config
  there means every save silently dies with the process and every launch
  reads the stale bundled snapshot. Frozen builds therefore persist to
  ``%LOCALAPPDATA%\\rivenforge\\user_config.json`` — a durable, per-user path
  that survives restarts, updates, and reinstalls.
- **Dev (running from source)**: the repo-local ``config/`` dir keeps working
  exactly as before, so development behavior is unchanged.

On the first frozen run (durable file missing) the bundled snapshot is copied
across once, so defaults/profiles shipped with the build seed the user file.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import UTC, datetime

from core.contracts import UserConfigDict

_BUNDLED_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config", "user_config.json")


def _resolve_config_path() -> str:
    if getattr(sys, "frozen", False):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "rivenforge", "user_config.json")
    return _BUNDLED_CONFIG_PATH


CONFIG_PATH = _resolve_config_path()
CURRENT_CONFIG_SCHEMA_VERSION = 1


def _seed_from_bundle_once() -> None:
    """First frozen run: copy the bundled config snapshot to the durable path."""
    if CONFIG_PATH == _BUNDLED_CONFIG_PATH:
        return  # dev mode — same file, nothing to seed
    if os.path.exists(CONFIG_PATH) or not os.path.exists(_BUNDLED_CONFIG_PATH):
        return
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        shutil.copy2(_BUNDLED_CONFIG_PATH, CONFIG_PATH)
    except Exception:
        pass  # defaults still apply; never block startup on a seed copy

_DEFAULTS = {
    "schema_version": CURRENT_CONFIG_SCHEMA_VERSION,
    "weapon":        "",
    "weapon_type":   "melee",
    "profiles":      [],
    "roll_limit":    100,
    "rag_threshold": 0.60,
    "animation_wait": 2.5,
    "roll_until_match": False,
    # When True the sidecar binds 0.0.0.0 (not just 127.0.0.1) so a paired
    # phone on the LAN can reach it. Always gated by the pairing token; a
    # sidecar restart is needed for a change to take effect.
    "phone_access_enabled": False,
    # Per-weapon manual stat preference order: {weapon_name: [stat, ...]}.
    # Highest-priority stat first. Biases scoring toward the user's favoured
    # combination for that specific weapon.
    "stat_hierarchies": {},
    # 1920x1080 Borderless Fullscreen estimates — recalibrate in Settings
    # Flow: CYCLE → YES(confirm kuva) → [animation] → CONFIRM → YES/NO(keep/revert)
    "button_coords": {
        "cycle_button":   [960, 820],   # "CYCLE FOR X KUVA"
        "cycle_yes":      [396, 247],   # YES on "Are you sure?" dialog
        "confirm_button": [638, 584],   # CONFIRM (two-card view)
        "keep_yes":       [487, 363],   # YES on "Cycle Riven into current selection?"
        "keep_no":        [665, 363],   # NO on same dialog
    },
}


def _backup_config() -> None:
    if not os.path.exists(CONFIG_PATH):
        return
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    backup_path = f"{CONFIG_PATH}.bak.{stamp}"
    shutil.copy2(CONFIG_PATH, backup_path)


def _migrate_config(data: dict) -> dict:
    version = int(data.get("schema_version", 0))
    if version == CURRENT_CONFIG_SCHEMA_VERSION:
        return data
    _backup_config()
    if version == 0:
        data["schema_version"] = CURRENT_CONFIG_SCHEMA_VERSION
        return data
    raise ValueError(f"Unsupported config schema_version: {version}")


def load_config() -> UserConfigDict:
    _seed_from_bundle_once()
    if not os.path.exists(CONFIG_PATH):
        return dict(_DEFAULTS)
    try:
        with open(CONFIG_PATH) as f:
            data = json.load(f)
        data = _migrate_config(data)
        # Fill in missing keys with defaults
        for k, v in _DEFAULTS.items():
            data.setdefault(k, v)
        save_config(data)
        return data
    except Exception:
        return dict(_DEFAULTS)


def save_config(cfg: UserConfigDict) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
