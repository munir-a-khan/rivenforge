"""
Warframe.Market riven price lookup.

Queries the WFM auction search API to get live platinum prices for
riven rolls matching the current stats. Used as a signal in RAG scoring
to favour rolls that actually sell for plat.

API endpoint:
  GET https://api.warframe.market/v1/auctions/search
      ?type=riven
      &weapon_url_name=<weapon>
      &positive_stats=<stat1>,<stat2>
      &sort_by=price_asc

Rate limit: 3 req/s  →  we cache per (weapon, frozenset(pos_stats)) for
CACHE_TTL seconds so we don't hammer WFM during a rolling session.

Melee fallback priority (user requirement):
  When no riven auction data exists for a weapon, or the weapon is a
  melee, we apply a hard-coded stat priority list:
    Priority positives : Critical Damage  >  Range  (then other hits)
    Penalty negatives  : Impact / Puncture / Slash / Finisher Damage
  This is the "CD > Range > neg IPS/Fin" rule the user specified.
"""

import time
import urllib.request
import urllib.parse
import json
import re
import threading
from typing import Optional

# ── Constants ────────────────────────────────────────────────────────────────

WFM_API  = "https://api.warframe.market/v1"
CACHE_TTL = 300   # seconds — 5 minutes per (weapon, stats) combo
_TIMEOUT  = 6     # HTTP request timeout in seconds

# ── Canonical stat name → WFM url_name ───────────────────────────────────────
# Source: GET /v1/riven/attributes
STAT_TO_WFM: dict[str, str] = {
    "critical chance":             "critical_chance",
    "critical damage":             "critical_damage",
    "multishot":                   "multishot",
    "damage":                      "base_damage_/_melee_damage",
    "melee damage":                "base_damage_/_melee_damage",
    "fire rate":                   "fire_rate_/_attack_speed",
    "attack speed":                "fire_rate_/_attack_speed",
    "reload speed":                "reload_speed",
    "status chance":               "status_chance",
    "status duration":             "status_duration",
    "range":                       "range",
    "combo duration":              "combo_duration",
    "initial combo":               "chance_to_gain_extra_combo_count",
    "heavy attack efficiency":     "channeling_efficiency",
    "slide critical chance":       "critical_chance_on_slide_attack",
    "finisher damage":             "finisher_damage",
    "electricity":                 "electric_damage",
    "toxin":                       "toxin_damage",
    "heat":                        "heat_damage",
    "cold":                        "cold_damage",
    "slash":                       "slash_damage",
    "impact":                      "impact_damage",
    "puncture":                    "puncture_damage",
    "recoil":                      "recoil",
    "zoom":                        "zoom",
    "projectile flight speed":     "projectile_speed",
    "punch through":               "punch_through",
    "magazine capacity":           "magazine_capacity",
    "ammo maximum":                "ammo_maximum",
    "damage to corpus":            "damage_vs_corpus",
    "damage to infested":          "damage_vs_infested",
    "damage to grineer":           "damage_vs_grineer",
}

# ── Melee priority / penalty lists ───────────────────────────────────────────
# When no WFM data available (or for melee weapons), use this to score:
#   Priority positives: CD first, then Range, then other desired hits
#   Penalised positives (dead weight on melee unless specifically wanted):
#     IPS (Impact / Puncture / Slash), Finisher Damage

MELEE_PRIORITY_POS = [
    "critical damage",    # highest priority
    "range",
    "attack speed",
    "critical chance",
    "multishot",
    "status chance",
]
MELEE_PENALTY_POS = [
    "impact",
    "puncture",
    "slash",
    "finisher damage",
]

# ── In-memory cache: (weapon_url, frozenset(pos_wfm)) → (timestamp, result) ─
_cache: dict = {}
_cache_lock = threading.Lock()


# ── Name helpers ─────────────────────────────────────────────────────────────

def weapon_to_url(weapon_name: str) -> str:
    """
    Convert a weapon display name to a WFM url_name.
    "Galatine Prime" → "galatine_prime"
    "Arca Plasmor"   → "arca_plasmor"
    """
    name = weapon_name.strip().lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    name = name.strip("_")
    return name


def stat_to_wfm(stat_name: str) -> Optional[str]:
    """
    Convert a canonical stat name (from parser.py) to a WFM url_name.
    Returns None if stat is not in the mapping.
    """
    return STAT_TO_WFM.get(stat_name.lower())


# ── WFM API fetch ─────────────────────────────────────────────────────────────

def _fetch_auctions(weapon_url: str, pos_wfm: list[str]) -> list[dict]:
    """
    Call WFM auction search API. Returns raw auction list or [] on error.

    We search for rivens that have ALL the positive stats we want — this
    gives us a price signal for "how much does a roll like this sell for?"
    """
    params = {
        "type":             "riven",
        "weapon_url_name":  weapon_url,
        "sort_by":          "price_asc",
    }
    if pos_wfm:
        params["positive_stats"] = ",".join(pos_wfm)

    url = f"{WFM_API}/auctions/search?" + urllib.parse.urlencode(params)

    try:
        req = urllib.request.Request(
            url,
            headers={
                "Platform":    "pc",
                "Language":    "en",
                "User-Agent":  "WFRivenPicker/1.0",
                "Accept":      "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("payload", {}).get("auctions", [])
    except Exception:
        return []


def _extract_buyout_prices(auctions: list[dict]) -> list[int]:
    """
    Extract buyout prices from auction list (skip auctions with no buyout).
    Only include auctions that are 'online' or 'ingame' (seller available).
    """
    prices = []
    for a in auctions:
        # Filter for active sellers only
        owner = a.get("owner", {})
        status = owner.get("status", "")
        if status not in ("ingame", "online"):
            continue
        bp = a.get("buyout_price")
        if bp and isinstance(bp, int) and bp > 0:
            prices.append(bp)
    return sorted(prices)


# ── Public price query ────────────────────────────────────────────────────────

def get_price_signal(weapon: str, parsed_stats: dict,
                     weapon_type: str = "") -> dict:
    """
    Query WFM for the current riven market price matching these stats.

    Returns:
        {
          "plat_low":    int | None,   # lowest buyout from online sellers
          "plat_median": int | None,   # median buyout
          "plat_score":  float,        # 0.0–1.0 normalised price signal
          "sample_size": int,          # how many auctions found
          "source":      str,          # "wfm" | "melee_fallback" | "none"
          "melee_bonus": float,        # extra score from melee priority
          "notes":       list[str],
        }
    """
    rolled_pos = [s["stat"].lower() for s in parsed_stats.get("positives", [])]
    rolled_neg = [s["stat"].lower() for s in parsed_stats.get("negatives", [])]

    # ── Melee priority bonus (always computed regardless of WFM data) ─────────
    melee_bonus = 0.0
    is_melee    = weapon_type.lower() in ("melee", "stat sticks")
    melee_notes = []

    if is_melee:
        # Priority multiplier: CD is worth most, Range second
        for i, priority_stat in enumerate(MELEE_PRIORITY_POS):
            if any(priority_stat in p for p in rolled_pos):
                # CD = +0.15, Range = +0.12, others = +0.08
                bonus = max(0.15 - i * 0.03, 0.05)
                melee_bonus += bonus
                melee_notes.append(f"+{bonus:.2f} melee priority: {priority_stat}")

        # IPS/Fin penalty on positives (dead weight unless user wants them)
        for penalty_stat in MELEE_PENALTY_POS:
            if any(penalty_stat in p for p in rolled_pos):
                melee_bonus -= 0.12
                melee_notes.append(f"-0.12 melee penalty (dead pos): {penalty_stat}")

        melee_bonus = max(-0.3, min(0.3, melee_bonus))  # cap ±0.30

    # ── Build WFM stat list ───────────────────────────────────────────────────
    pos_wfm = [w for w in (stat_to_wfm(s) for s in rolled_pos) if w]
    weapon_url = weapon_to_url(weapon)

    # ── Cache check ──────────────────────────────────────────────────────────
    cache_key = (weapon_url, frozenset(pos_wfm))
    with _cache_lock:
        if cache_key in _cache:
            ts, cached = _cache[cache_key]
            if time.monotonic() - ts < CACHE_TTL:
                # Return cached price data + freshly computed melee bonus
                result = dict(cached)
                result["melee_bonus"] = melee_bonus
                result["notes"]       = cached["notes"] + melee_notes
                return result

    # ── Fetch from WFM ───────────────────────────────────────────────────────
    auctions = _fetch_auctions(weapon_url, pos_wfm)
    prices   = _extract_buyout_prices(auctions)

    plat_low    = prices[0]             if prices else None
    plat_median = prices[len(prices)//2] if prices else None

    # ── Normalise to 0–1 score ────────────────────────────────────────────────
    # Price brackets (rough plat market tiers for rivens):
    #   < 50p  → junk (0.0)
    #   50–150 → low (0.2)
    #   150–300 → decent (0.4)
    #   300–600 → good (0.6)
    #   600–1000 → great (0.8)
    #   1000+  → exceptional (1.0)
    if plat_median is None:
        plat_score = 0.5   # no data — neutral, don't penalise
        source = "none"
    else:
        source = "wfm"
        p = plat_median
        if   p < 50:    plat_score = 0.0
        elif p < 150:   plat_score = 0.2
        elif p < 300:   plat_score = 0.4
        elif p < 600:   plat_score = 0.6
        elif p < 1000:  plat_score = 0.8
        else:           plat_score = 1.0

    notes = []
    if plat_median is not None:
        notes.append(
            f"WFM: {len(prices)} listings | "
            f"low {plat_low}p | median {plat_median}p"
        )
    else:
        notes.append("WFM: no listings found for these stats")
    notes += melee_notes

    result = {
        "plat_low":    plat_low,
        "plat_median": plat_median,
        "plat_score":  plat_score,
        "sample_size": len(prices),
        "source":      source,
        "melee_bonus": melee_bonus,
        "notes":       notes,
    }

    # Cache only the price parts (melee_bonus is recomputed fresh each call)
    cache_entry = {
        "plat_low":    plat_low,
        "plat_median": plat_median,
        "plat_score":  plat_score,
        "sample_size": len(prices),
        "source":      source,
        "notes":       notes[:1],   # only WFM note, not melee notes
    }
    with _cache_lock:
        _cache[cache_key] = (time.monotonic(), cache_entry)

    return result


def clear_cache():
    with _cache_lock:
        _cache.clear()
