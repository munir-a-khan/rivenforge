"""
Load stat_aliases.json and expose ALL_STATS list.
Placed in data/ so both gui/ and core/ can import it without circular deps.
"""

import json
import os

_PATH = os.path.join(os.path.dirname(__file__), "stat_aliases.json")

with open(_PATH) as f:
    _ALIASES = json.load(f)

# Full canonical stat names
ALL_STATS: list[str] = sorted(set(_ALIASES.values()))

# Abbrev → full name
ABBREV_TO_FULL: dict[str, str] = dict(_ALIASES)

# Full name (lower) → full name (canonical)
FULL_LOWER: dict[str, str] = {v.lower(): v for v in _ALIASES.values()}
