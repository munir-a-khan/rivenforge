"""
Load/save user_config.json from the config/ directory.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime

from core.contracts import UserConfigDict

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config", "user_config.json")
CURRENT_CONFIG_SCHEMA_VERSION = 1

_DEFAULTS = {
    "schema_version": CURRENT_CONFIG_SCHEMA_VERSION,
    "weapon":        "",
    "weapon_type":   "melee",
    "profiles":      [],
    "roll_limit":    100,
    "rag_threshold": 0.60,
    "animation_wait": 2.5,
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
