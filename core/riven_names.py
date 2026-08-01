"""
Decode a Warframe riven mod's generated NAME back into its stats.

Every riven's name is deterministically built from its attributes, so reading
the big, high-contrast name (which OCRs far more reliably than the small stat
rows) tells us the POSITIVE stats without having to read them line by line.
Only the negative then has to be read from the stat lines.

Naming grammar (from the WARFRAME wiki "Riven Mods" naming section):
  - Every attribute has a PREFIX syllable and a SUFFIX syllable.
  - The full name is  ``<weapon> <Grammar>``  where the grammar part encodes
    the stats: the highest-magnitude stat's PREFIX, then any middle stats'
    PREFIX, then the lowest stat's SUFFIX — e.g. "Sati-critaata" =
    Sati (Multishot) + crita (Critical Chance) + ata (Damage).
  - A hyphen separates the first stat's prefix from the rest; two-stat names
    have no hyphen (e.g. "Saticron" = Sati + cron = Multishot + Crit Chance).

We only care about the SET of stats a name encodes (order/magnitude is not
recoverable from the displayed percentages, and isn't needed to match a
profile), so the decoder returns a set of canonical stat IDs.

Reference: https://wiki.warframe.com/w/Riven_Mods
"""

from __future__ import annotations

# (canonical stat_id, prefix syllable, suffix syllable) for every attribute.
# stat_id must match core.stat_registry.make_stat_id(canonical name).
_ATTRIBUTES: list[tuple[str, str, str]] = [
    ("initial_combo",           "laci",  "nus"),   # Combo Count Chance
    ("ammo_maximum",            "ampi",  "bin"),
    ("damage_to_corpus",        "manti", "tron"),
    ("damage_to_grineer",       "argi",  "con"),
    ("damage_to_infested",      "pura",  "ada"),
    ("cold",                    "geli",  "do"),
    ("combo_duration",          "tempi", "nem"),
    ("critical_chance",         "crita", "cron"),
    ("slide_critical_chance",   "pleci", "nent"),
    ("critical_damage",         "acri",  "tis"),
    ("damage",                  "visi",  "ata"),   # Base Damage / Melee Damage
    ("electricity",             "vexi",  "tio"),
    ("heat",                    "igni",  "pha"),
    ("finisher_damage",         "exi",   "cta"),
    ("fire_rate",               "croni", "dra"),   # Fire Rate / Attack Speed
    ("projectile_flight_speed", "conci", "nak"),
    ("initial_combo",           "para",  "um"),
    ("impact",                  "magna", "ton"),
    ("magazine_capacity",       "arma",  "tin"),
    ("heavy_attack_efficiency", "forti", "us"),
    ("multishot",               "sati",  "can"),
    ("toxin",                   "toxi",  "tox"),
    ("punch_through",           "lexi",  "nok"),
    ("puncture",                "insi",  "cak"),
    ("reload_speed",            "feva",  "tak"),
    ("range",                   "locti", "tor"),
    ("slash",                   "sci",   "sus"),
    ("status_chance",           "hexa",  "dex"),
    ("status_duration",         "deci",  "des"),
    ("recoil",                  "zeti",  "mag"),
    ("zoom",                    "hera",  "lis"),
]

# Melee weapons reuse two attribute syllables for their melee analogues.
_MELEE_REMAP = {"damage": "melee_damage", "fire_rate": "attack_speed"}

_PREFIX: dict[str, str] = {}
_SUFFIX: dict[str, str] = {}
for _sid, _pre, _suf in _ATTRIBUTES:
    _PREFIX.setdefault(_pre, _sid)
    _SUFFIX.setdefault(_suf, _sid)


def _match_prefix_chain(head: str) -> list[str] | None:
    """
    Segment ``head`` entirely into PREFIX syllables (longest-match, with
    backtracking). Returns the list of stat_ids, or None if it can't be
    segmented cleanly.
    """
    if not head:
        return []
    # Longest candidate first so e.g. "croni" wins over a shorter false match.
    for pre in sorted(_PREFIX, key=len, reverse=True):
        if head.startswith(pre):
            rest = _match_prefix_chain(head[len(pre):])
            if rest is not None:
                return [_PREFIX[pre], *rest]
    return None


def decode_riven_grammar(grammar: str, *, melee: bool = False) -> set[str] | None:
    """
    Decode the grammar portion of a riven name (weapon already stripped) into
    the set of canonical stat IDs it encodes.

    Returns None if the string can't be decoded (OCR garble or an unknown
    pattern) so callers can fall back to stat-line OCR.

    ``melee`` remaps the two shared syllables (Damage→Melee Damage,
    Fire Rate→Attack Speed) to their melee analogues.
    """
    s = "".join(ch for ch in grammar.lower() if ch.isalpha())
    if len(s) < 4:
        return None

    # The name ends in the lowest stat's SUFFIX; everything before it is a
    # chain of PREFIX syllables. Try each suffix as the ending.
    for suf in sorted(_SUFFIX, key=len, reverse=True):
        if s.endswith(suf):
            head = s[: len(s) - len(suf)]
            chain = _match_prefix_chain(head)
            if chain is not None:
                ids = {*chain, _SUFFIX[suf]}
                if len(ids) < 2:
                    # A real riven has >= 2 positives, so a "name" decoding to a
                    # single stat is an OCR fragment — keep trying / fall back.
                    continue
                if melee:
                    ids = {_MELEE_REMAP.get(i, i) for i in ids}
                return ids
    return None


def strip_weapon(name: str, weapon: str) -> str:
    """
    Remove the leading weapon name from a full riven name, returning just the
    grammar part. "Quatz Sati-lexitox" + weapon "quatz" -> "Sati-lexitox".

    Falls back to taking the text after the first space when the weapon prefix
    doesn't match (OCR misread of the weapon, or a multi-word weapon).
    """
    n = name.strip()
    w = (weapon or "").strip()
    if w and n.lower().startswith(w.lower()):
        return n[len(w):].strip()
    # Weapon prefix didn't match (OCR misread it, or config weapon differs):
    # drop the FIRST whitespace token (the weapon) and keep the rest, which is
    # the grammar — possibly split across a line wrap ("Sati- ampicron").
    parts = n.split()
    return " ".join(parts[1:]) if len(parts) > 1 else n


def decode_riven_name(name: str, weapon: str = "", *, melee: bool = False) -> set[str] | None:
    """Full-name convenience: strip the weapon, then decode the grammar."""
    return decode_riven_grammar(strip_weapon(name, weapon), melee=melee)


def reconcile_parsed_with_name(
    parsed: dict, name: str, weapon: str = "", *, melee: bool = False
) -> tuple[dict, set[str] | None]:
    """
    Correct a stat-line OCR result using the (far more reliable) riven NAME.

    The name deterministically encodes the positive stats, so we take them as
    authoritative and keep OCR only for the negative and for stat VALUES:

      - positives = decoded-name stats MINUS whatever OCR read as the negative
        (in a 2-positive+curse riven the name's lowest slot IS the negative).
      - if the name yields fewer than the visible positive count and OCR found
        an extra positive (the rare 3-positive+curse case, where one positive
        is not in the name), that OCR positive is added back, capped at 3.
      - each positive keeps its OCR value when that stat was read, else 0.
      - the negative is taken from OCR unchanged.

    Returns ``(corrected_parsed, decoded_ids)``. If the name can't be decoded,
    the original parsed dict is returned unchanged with ``None``.
    """
    from core.stat_registry import display_name, normalize_stat

    decoded = decode_riven_name(name, weapon, melee=melee)
    if not decoded:
        return parsed, None

    def _id(stat: str) -> str | None:
        ref = normalize_stat(stat)
        return ref.id if ref else None

    ocr_pos_val = {}
    for p in parsed.get("positives", []):
        pid = _id(str(p.get("stat", "")))
        if pid:
            ocr_pos_val[pid] = float(p.get("value", 0.0))

    neg_entries = list(parsed.get("negatives", []))

    # A riven has AT MOST ONE curse. OCR sign-noise can mark several stat lines
    # negative at once; the old code subtracted EVERY such stat from the
    # name-decoded set, which collapsed a good 2-3 positive roll down to a single
    # positive (the field bug). The name is authoritative for the stat SET, so
    # only ONE of its stats may be the curse: prefer a negative the name actually
    # contains, and among those the most-negative value. Everything else OCR
    # flagged negative is treated as sign noise and left as a positive.
    def _fval(e: dict) -> float:
        try:
            return float(e.get("value", 0.0))
        except (TypeError, ValueError):
            return 0.0

    curse_id = None
    curse_entry = None
    if neg_entries:
        in_name = [n for n in neg_entries if _id(str(n.get("stat", ""))) in decoded]
        out_name = [n for n in neg_entries if n not in in_name]
        # A riven ALWAYS has 2 or 3 positives — "1 positive + 1 negative" does
        # not exist in-game. So an in-name stat may only be the curse when the
        # name carries 3 stats; a 2-stat name is 2 POSITIVES by definition, and
        # an OCR "negative" on one of them is sign noise (field bug roll #22:
        # 'Zetiata' shown as Recoil / -Damage). With a 2-stat name the curse,
        # if any, must be an out-of-name negative.
        if len(decoded) >= 3 and in_name:
            curse_entry = min(in_name, key=_fval)
        elif out_name:
            curse_entry = min(out_name, key=_fval)
        if curse_entry is not None:
            curse_id = _id(str(curse_entry.get("stat", "")))

    # The non-curse "negatives" were sign noise; they are restored as positives
    # below, so they must ALSO be dropped from the negatives list. Leaving them
    # there listed the same stat as both positive and negative, and rules.evaluate
    # checks every negative against acceptable_negatives — so a phantom negative
    # rejected an otherwise-good roll (the same under-read symptom, one stage later).
    neg_entries = [curse_entry] if curse_entry is not None else []

    pos_ids = [i for i in decoded if i != curse_id]

    # Rare 3-positive+curse: the name omits one positive. Fill from OCR.
    if len(pos_ids) < 3:
        for pid in ocr_pos_val:
            if pid not in pos_ids and pid != curse_id and len(pos_ids) < 3:
                pos_ids.append(pid)

    positives = [{"stat": display_name(i), "value": ocr_pos_val.get(i, 0.0)} for i in pos_ids]

    corrected = dict(parsed)
    corrected["positives"] = positives
    corrected["negatives"] = neg_entries
    total = len(positives) + len(neg_entries)
    if len(positives) > 3 or len(neg_entries) > 1:
        corrected["status"] = "invalid"
    elif total >= 2:
        corrected["status"] = "ok"
    elif total == 1:
        corrected["status"] = "partial"
    else:
        corrected["status"] = "empty"
    return corrected, decoded
