"""
Stat normalization and lookup helpers.

The stable ID is lowercase snake_case derived from the canonical stat name.
The display name remains the Warframe-facing name from data/stat_aliases.json.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz, process

from core.models import StatRef

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ALIAS_PATH = DATA_DIR / "stat_aliases.json"


def make_stat_id(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return re.sub(r"_+", "_", cleaned)


@lru_cache(maxsize=1)
def _load_aliases() -> dict[str, str]:
    with ALIAS_PATH.open(encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def canonical_stats() -> tuple[StatRef, ...]:
    names = sorted(set(_load_aliases().values()))
    return tuple(StatRef(id=make_stat_id(name), name=name) for name in names)


@lru_cache(maxsize=1)
def _name_by_id() -> dict[str, str]:
    return {stat.id: stat.name for stat in canonical_stats()}


@lru_cache(maxsize=1)
def _id_by_normalized_name() -> dict[str, str]:
    mapping: dict[str, str] = {}
    aliases = _load_aliases()
    for alias, canonical in aliases.items():
        stat_id = make_stat_id(canonical)
        mapping[alias.lower()] = stat_id
        mapping[canonical.lower()] = stat_id
    return mapping


def display_name(stat_id: str) -> str:
    return _name_by_id().get(stat_id, stat_id)


# Decorative annotations Warframe appends to stat names on certain weapon
# classes. They change the displayed VALUE in-game but NOT the rolled stat's
# identity — "Critical Chance (x2 for Heavy Attacks)" is still the
# Critical Chance stat; "-57% Fire Rate (x2 for Bows)" is still Fire Rate.
#
# We match the GENERIC shape "(x<digit> for <anything>)" rather than enumerate
# every weapon class Warframe might ever ship (Heavy Attacks, Bows, Shotguns,
# Beam, etc.). Same for "(when wielding <anything>)".
_DECORATIVE_NOISE = [
    re.compile(r"\(\s*x\s*\d+\s+for\s+[a-z\s]+?\s*\)", re.IGNORECASE),
    re.compile(r"\(\s*when\s+wielding\s+[a-z\s]+?\s*\)", re.IGNORECASE),
]


def _strip_decorative_noise(text: str) -> str:
    cleaned = text
    for pat in _DECORATIVE_NOISE:
        cleaned = pat.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_stat(raw: str, fuzzy_threshold: int = 70) -> StatRef | None:
    text = _strip_decorative_noise(raw.strip())
    if not text:
        return None

    by_name = _id_by_normalized_name()
    direct = by_name.get(text.lower())
    if direct:
        return StatRef(id=direct, name=display_name(direct))

    choices = [stat.name for stat in canonical_stats()]
    match = process.extractOne(text.title(), choices, scorer=fuzz.token_sort_ratio)
    if not match:
        return None
    name, score, _ = match
    if score < fuzzy_threshold:
        return None
    stat_id = make_stat_id(name)
    return StatRef(id=stat_id, name=name)


def find_stat_in(text: str, threshold: int = 82) -> StatRef | None:
    """
    Find the best canonical stat *inside* a noisy text span.

    Unlike ``normalize_stat`` (which fuzzy-matches the WHOLE string and so
    gets diluted by trailing garbage), this scans for a stat name that
    appears as a substring. It is what recovers a stat from OCR bleed like:

        "a% status Duration Nukor Acriata"  -> Status Duration
        "% Ammo Maximum x"                  -> Ammo Maximum
        "ypuncture"                         -> Puncture

    Scoring uses ``partial_ratio`` (best-substring match). Ties are broken
    toward the LONGER canonical name so "Damage to Grineer" wins over the
    bare "Damage" when both are present, but a ``token_set_ratio`` gate
    prevents a short name like "Slide Critical Chance" from stealing a plain
    "Critical Chance" (its extra tokens tank the set ratio).
    """
    text = _strip_decorative_noise(text.strip())
    if not text or not any(c.isalpha() for c in text):
        return None

    # Fast path: an exact alias/name is present verbatim. Strip leading
    # non-letters first ("% Additional Combo Count Chance" -> the alias) so a
    # unit character left on the value span doesn't defeat the exact lookup.
    core = re.sub(r"^[^A-Za-z]+", "", text)
    direct = normalize_stat(core)
    if direct is not None:
        return direct

    low = text.lower()
    best: StatRef | None = None
    best_key: tuple[float, float, int] = (-1.0, -1.0, -1)
    for stat in canonical_stats():
        name_low = stat.name.lower()
        partial = fuzz.partial_ratio(name_low, low)
        if partial < threshold:
            continue
        set_ratio = fuzz.token_set_ratio(name_low, low)
        # Rank primarily on partial match, then how cleanly the whole name is
        # accounted for (set_ratio), then name length as a final tiebreak.
        key = (partial, set_ratio, len(stat.name))
        if key > best_key:
            best_key = key
            best = stat
    return best


def normalize_many(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    ids: list[str] = []
    seen: set[str] = set()
    for value in values:
        ref = normalize_stat(value)
        if ref and ref.id not in seen:
            ids.append(ref.id)
            seen.add(ref.id)
    return tuple(ids)
