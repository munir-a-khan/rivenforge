"""
RAG scorer — pure Python, zero DLL dependencies.

Uses the TF-IDF index built by ingest.py instead of ChromaDB + neural embeddings.
Scoring = direct stat alignment (primary) + WFM market price (secondary) + TF-IDF (tertiary).

Score composition (all components 0.0–1.0, combined into final 0.0–1.0):
  55%  Tier-list alignment  — how well the roll matches the community tier list
  30%  WFM price signal     — live plat price for rivens with these stats
  15%  TF-IDF similarity    — semantic match of the roll query to tier list entries

Melee handling:
  For melee weapons, wfm.py applies a priority bonus/penalty on top of the
  price signal based on: CD > Range > other, and IPS/Fin as dead-weight
  positives.  This surfaces even when WFM has no listings for a weapon.
"""

import os

from core.contracts import ParsedRollDict, RagScoreDict
from rag.ingest import search, weapon_lookup, is_ready, reset as _reset_index

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def score(parsed_stats: ParsedRollDict | dict, weapon: str, weapon_type: str = "") -> RagScoreDict:
    """
    Score a roll against the tier list knowledge base + WFM market prices.

    Returns:
        {
          "score":        float,       # 0.0 – 1.0 combined score
          "notes":        [str],
          "weapon_data":  dict|None,
          "plat_low":     int|None,    # lowest WFM buyout price (online sellers)
          "plat_median":  int|None,    # median WFM buyout price
          "plat_score":   float,       # 0.0–1.0 normalised plat signal
          "melee_bonus":  float,       # extra from CD/Range priority on melees
          "wfm_source":   str,         # "wfm" | "none"
        }
    """
    # ── 1. Direct weapon lookup in tier list ─────────────────────────────────
    weapon_data = None
    try:
        matches = weapon_lookup(weapon)
        if matches:
            weapon_data = matches[0]
    except Exception:
        pass

    # ── 2. TF-IDF semantic search ─────────────────────────────────────────────
    pos_str  = " ".join(f"+{s['stat']}" for s in parsed_stats.get("positives", []))
    neg_str  = " ".join(f"-{s['stat']}" for s in parsed_stats.get("negatives", []))
    query    = f"Weapon: {weapon}. Roll: {pos_str} {neg_str}."

    sem_hits = []
    try:
        sem_hits = search(query, n=3)
    except Exception:
        pass

    # ── 3. Tier-list alignment score (0.0–1.0) ───────────────────────────────
    alignment = _alignment_score(parsed_stats, weapon_data) if weapon_data else 0.5

    # ── 4. TF-IDF semantic score (0.0–1.0) ───────────────────────────────────
    sem_score = 0.5  # neutral default when no index hits
    if sem_hits:
        hit_weapons  = [h["weapon"].lower() for h in sem_hits]
        weapon_hits  = sum(1 for w in hit_weapons if w == weapon.lower())
        sem_score    = weapon_hits / len(sem_hits)

    # ── 5. WFM live price signal ──────────────────────────────────────────────
    plat_score   = 0.5   # neutral default (no data = don't punish)
    plat_low     = None
    plat_median  = None
    melee_bonus  = 0.0
    wfm_source   = "none"
    wfm_notes    = []

    try:
        from rag.wfm import get_price_signal
        wfm = get_price_signal(weapon, parsed_stats, weapon_type)
        plat_score  = wfm["plat_score"]
        plat_low    = wfm["plat_low"]
        plat_median = wfm["plat_median"]
        melee_bonus = wfm["melee_bonus"]
        wfm_source  = wfm["source"]
        wfm_notes   = wfm["notes"]
    except Exception:
        pass   # WFM fetch failed — fall back silently to neutral 0.5

    # ── 6. Combine all signals ────────────────────────────────────────────────
    # Weights: 55% tier-list alignment, 30% WFM price, 15% TF-IDF
    # Melee bonus is additive on top (already capped ±0.30 in wfm.py)
    combined = (
        0.55 * alignment
        + 0.30 * plat_score
        + 0.15 * sem_score
        + melee_bonus
    )
    # Clamp to [0.0, 1.0]
    final = round(max(0.0, min(1.0, combined)), 3)

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes = []
    if weapon_data:
        notes.append(
            f"Tier list: {weapon_data.get('positives_raw', '')} "
            f"| neg OK: {weapon_data.get('negatives_raw', '')}"
        )
        if weapon_data.get("notes"):
            notes.append(f"Notes: {weapon_data['notes']}")
    notes += wfm_notes

    return {
        "score":       final,
        "notes":       notes,
        "weapon_data": weapon_data,
        "plat_low":    plat_low,
        "plat_median": plat_median,
        "plat_score":  plat_score,
        "melee_bonus": melee_bonus,
        "wfm_source":  wfm_source,
    }


def _alignment_score(parsed_stats: dict, weapon_data: dict) -> float:
    """
    Measure how well the roll aligns with the tier list for this weapon.
    Returns 0.0–1.0.
    """
    desired_pos = set(s.lower() for s in weapon_data.get("positives", []))
    ok_neg      = set(s.lower() for s in weapon_data.get("negatives", []))

    rolled_pos  = [s["stat"].lower() for s in parsed_stats.get("positives", [])]
    rolled_neg  = [s["stat"].lower() for s in parsed_stats.get("negatives", [])]

    if not desired_pos:
        return 0.5

    hits      = sum(1 for s in rolled_pos if s in desired_pos)
    pos_score = hits / len(desired_pos)
    bad_negs  = sum(1 for s in rolled_neg if ok_neg and s not in ok_neg)
    penalty   = 0.3 * bad_negs

    return max(0.0, min(1.0, pos_score - penalty))


def is_db_ready() -> bool:
    return is_ready()


def reset_client():
    """Reset cached data (call after a rebuild)."""
    _reset_index()
    try:
        from rag.wfm import clear_cache
        clear_cache()
    except Exception:
        pass
