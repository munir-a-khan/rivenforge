"""
Parse raw OCR text lines into structured riven stats.

Warframe riven stats appear as:
  +125.3% Critical Chance
  +80.2% Puncture
  -30.1% Reload Speed

This module extracts sign, value, and stat name, then normalises
the stat name against our known alias map using fuzzy matching.
"""

import re
from typing import Literal

from core.contracts import ParsedRollDict
from core.models import ParseResult, ParserIssue, ParseStatus, RivenStat
from core.stat_registry import canonical_stats, find_stat_in, normalize_stat

# Canonical full stat names, kept for compatibility with older callers/tests.
CANONICAL_STATS = [stat.name for stat in canonical_stats()]

# Regex: optional sign (ASCII or Unicode), number (with optional decimal),
# optional %, then stat name.
# Examples: "+125.3% Critical Chance", "−30.1% Reload Speed", "+80.2 Puncture"
# Unicode minus U+2212 included explicitly in case vision.py normalisation
# didn't run (belt-and-suspenders).
_STAT_RE = re.compile(
    r"([+\-\u2212\u2013\u2014]?)\s*(\d+\.?\d*)\s*%?\s*(.+)",
    re.IGNORECASE,
)

# Lines that should be skipped (UI text, not stats).
# NOTE: "combo duration" removed — it IS a valid riven stat name.
#       Only skip "initial combo" (it's a mod property, not a rollable stat line).
_SKIP_PHRASES = {
    "mr", "mastery rank", "cycle", "kuva", "confirm", "remaining",
    "fits in", "show ranked", "close", "initial combo",
    "riven mod", "veiled",
}

# A "stat line" starts with an optional sign and a digit; everything else is
# either UI noise or a wrapped continuation of the previous stat name.
_STAT_LINE_START_RE = re.compile(r"^\s*[+\-−–—]?\s*\d")

# Stat IDs whose displayed sign is INVERTED relative to whether the value
# benefits the player. Recoil is the obvious example: +73.1% Recoil makes
# the gun harder to control (bad), -30% Recoil makes it easier (good). The
# in-game card still prints the raw delta, but the rule engine + scoring
# need to know which "side" a rolled Recoil sits on.
#
# When the parser sees a line for an inverted stat, it flips the sign and
# polarity tag so the rest of the pipeline can treat it uniformly with all
# other stats (positives have +value and polarity="positive"; negatives
# have -value and polarity="negative").
_INVERTED_STAT_IDS: set[str] = {"recoil"}

# Physical limits of a real Warframe riven. A rolled riven has AT MOST three
# positive stats and AT MOST one negative. If we parse more than this, OCR has
# bled in an adjacent card (the two-card cycle-compare view puts the OLD riven
# on the left) or a weapon name — the read is corrupt and must never be trusted
# for a KEEP decision. See the Quatz Critapha mis-keep in the diagnostics:
# 4 positives were parsed (2 real + 2 left-card bleed) and it got kept.
_MAX_POSITIVES = 3
_MAX_NEGATIVES = 1


def _looks_like_stat_name_continuation(line: str) -> bool:
    """
    True when a line looks like the second visual row of a wrapped stat name
    (e.g. "for Slide Attack", "(x2 for Heavy Attacks)", "Combo Count").
    """
    t = line.strip()
    if not t or len(t) > 40:
        return False
    if _STAT_LINE_START_RE.match(t):
        return False
    lower = t.lower()
    if any(skip in lower for skip in _SKIP_PHRASES):
        return False
    return any(c.isalpha() for c in t)


def merge_wrapped_stat_lines(lines: list[str] | tuple[str, ...]) -> list[str]:
    """
    Join Warframe UI line-wraps back into single stat lines.

    The in-game riven card wraps long stat names like "Critical Chance for
    Slide Attack" onto a second visual line, and OCR returns each visual
    line separately. Without this step, the parser sees only
    "+128.4% Critical Chance" and the slide modifier is silently lost,
    which then collides with any other "Critical Chance" line on the same
    riven and the duplicate gets dropped.
    """
    merged: list[str] = []
    for raw in lines:
        line = (raw or "").strip()
        if not line:
            continue
        if merged and _looks_like_stat_name_continuation(line):
            merged[-1] = f"{merged[-1]} {line}".strip()
        else:
            merged.append(line)
    return merged


def _normalise_stat(raw: str) -> str | None:
    """
    Fuzzy-match a raw stat name (possibly with OCR errors) to a canonical name.
    Returns None if confidence < 70.
    """
    ref = normalize_stat(raw)
    return ref.name if ref else None


# A value anchor: an optional sign, then a number, then an OPTIONAL unit that
# OCR may have corrupted (``%`` misread as ``a%``, ``s`` for combo seconds, or
# nothing at all). We deliberately do NOT require the ``%`` \u2014 the log shows
# reads like ``-35a% Status Duration`` where the unit is mangled, and requiring
# a clean ``%`` would silently drop the whole (often negative) stat.
_VALUE_ANCHOR_RE = re.compile(r"([+\-\u2212\u2013\u2014])?\s*(\d+(?:\.\d+)?)")


# Faction damage multiplier, e.g. "x1.81 Damage to Corpus", "xO.58 Damage to
# Grineer" (OCR often reads the leading 0 as O, and may split "1.81" as "1 .81").
_FACTION_MULT_RE = re.compile(
    r"x\s*([0oO]?[\d.,\s]*\d)\s*(damage\s*to\s*(?:corpus|grineer|infested))",
    re.IGNORECASE,
)


def _extract_faction_multipliers(line: str) -> tuple[list[tuple[str, float, str]], str]:
    """
    Pull faction-damage multipliers out of a line and turn them into signed
    percentages. Returns ``(stats, cleaned_line)`` where each stat is
    ``(sign_str, magnitude, name)`` — magnitude is |percent| and sign_str is
    "+"/"-" so the caller applies the same polarity logic as any other stat.
    x > 1 → positive bonus; x < 1 → negative (curse).
    """
    stats: list[tuple[str, float, str]] = []

    def _repl(m: re.Match) -> str:
        raw = m.group(1).lower().replace("o", "0").replace(" ", "").replace(",", ".")
        try:
            mult = float(raw)
        except ValueError:
            return " "
        if mult <= 0 or mult > 10:  # sanity: real faction mults are ~0.4–2.0
            return " "
        pct = round((mult - 1.0) * 100.0, 1)
        stats.append(("+" if pct >= 0 else "-", abs(pct), m.group(2)))
        return " "

    cleaned = _FACTION_MULT_RE.sub(_repl, line)
    return stats, cleaned


def _extract_line_stats(line: str) -> list[tuple[str, float, str]]:
    """
    Pull EVERY (sign, value, name_text) stat from one OCR line.

    Warframe shows one stat per row, but OCR frequently merges rows or bleeds
    the weapon name in, e.g.::

        "+387% Ammo Maximum x1 .22 Damage to Infested Fire Rate"
        "-35a% status Duration Nukor Acriata"

    We anchor on each number, take the text up to the NEXT number as that
    stat's name span, and resolve it with ``find_stat_in`` (substring match),
    which shrugs off trailing weapon names and unit garbage. Multiplier tokens
    like ``x2`` / ``x1.22`` are skipped (a number immediately preceded by an
    ``x``), so combo/heavy-attack multipliers don't masquerade as stats.
    """
    anchors = list(_VALUE_ANCHOR_RE.finditer(line))
    out: list[tuple[str, float, str]] = []
    for i, m in enumerate(anchors):
        # Skip numbers that are not stat values:
        #   'x'  -> a multiplier token ("x2 for Heavy Attacks", "x1.22")
        #   '.'  -> an orphaned decimal fragment (OCR split "1.22" as "1 .22",
        #           leaving a stray "22" that would invent a phantom stat)
        # Walk back past spaces to the first real char before the (sign+)number.
        j = m.start() - 1
        while j >= 0 and line[j] == " ":
            j -= 1
        prev = line[j].lower() if j >= 0 else ""
        if prev in ("x", "."):
            continue
        sign_str = m.group(1) or ""
        try:
            value = float(m.group(2))
        except ValueError:
            continue
        name_span = line[m.end():anchors[i + 1].start()] if i + 1 < len(anchors) else line[m.end():]
        out.append((sign_str, value, name_span))
    return out


def parse_result(ocr_lines: list[str], confidence: float = 1.0) -> ParseResult:
    """
    Parse OCR text lines into typed riven data.

    A result is considered complete enough only when at least two stat lines
    are parsed. Single-stat or empty reads are marked partial/empty so rule
    evaluation can return REVIEW instead of KEEP/ROLL.
    """
    positives: list[RivenStat] = []
    negatives: list[RivenStat] = []
    issues: list[ParserIssue] = []
    seen_canonical: set[str] = set()

    ocr_lines = merge_wrapped_stat_lines(ocr_lines)

    for raw_line in ocr_lines:
        line = raw_line.strip()
        if not line:
            continue

        lower = line.lower()
        if any(skip in lower for skip in _SKIP_PHRASES):
            continue

        # Faction damage is shown as a MULTIPLIER, not a signed percent:
        # "x1.81 Damage to Corpus" = +81%, "x0.58 Damage to Corpus" = -42%.
        # Pull those out first (the normal extractor skips x-prefixed numbers as
        # combo multipliers) and rewrite them as signed-percent stat text.
        faction_stats, line = _extract_faction_multipliers(line)

        candidates = _extract_line_stats(line) if line.strip() else []
        candidates = faction_stats + candidates
        if not candidates:
            issues.append(ParserIssue("not_stat_line", "Line did not match stat format", line))
            continue

        for sign_str, value, name_raw in candidates:
            if value <= 0 or value > 999:
                issues.append(ParserIssue("impossible_value", "Stat value outside sanity range", line))
                continue

            ref = find_stat_in(name_raw)
            if not ref:
                issues.append(ParserIssue("unknown_stat", "Could not normalize stat name", line))
                continue

            if ref.id in seen_canonical:
                issues.append(ParserIssue("duplicate_stat", "Duplicate stat ignored", line))
                continue
            seen_canonical.add(ref.id)

            sign = -1 if sign_str in ("-", "\u2212", "\u2013", "\u2014") else 1
            # Recoil and similar inverted stats: the in-game card prints a raw
            # delta, but a positive delta is BAD for the player. Flip the sign
            # so the rest of the pipeline can compare apples to apples.
            beneficial = (sign > 0) ^ (ref.id in _INVERTED_STAT_IDS)
            signed_value = value if beneficial else -value
            polarity: Literal["positive", "negative"] = "positive" if beneficial else "negative"
            entry = RivenStat(
                stat_id=ref.id,
                name=ref.name,
                value=signed_value,
                polarity=polarity,
                raw_line=line,
            )
            if beneficial:
                positives.append(entry)
            else:
                negatives.append(entry)

    total = len(positives) + len(negatives)
    over_count = len(positives) > _MAX_POSITIVES or len(negatives) > _MAX_NEGATIVES
    if over_count:
        # More stats than a real riven can have — OCR bled in another card or
        # a weapon name. Refuse to trust it: INVALID routes to REVIEW/REVERT,
        # so a corrupt read can never win a KEEP.
        issues.append(ParserIssue(
            "impossible_stat_count",
            f"Parsed {len(positives)} positives / {len(negatives)} negatives; "
            f"a riven has at most {_MAX_POSITIVES} positives and {_MAX_NEGATIVES} negative. "
            "Likely adjacent-card bleed.",
        ))
        status = ParseStatus.INVALID
    elif total == 0:
        status = ParseStatus.EMPTY
    elif total < 2:
        status = ParseStatus.PARTIAL
    else:
        status = ParseStatus.OK

    return ParseResult(
        positives=tuple(positives),
        negatives=tuple(negatives),
        raw_lines=tuple(ocr_lines),
        issues=tuple(issues),
        confidence=confidence,
        status=status,
    )


def parse(ocr_lines: list[str]) -> ParsedRollDict:
    """
    Parse a list of OCR text lines into a stats dict.

    Returns:
    {
      "positives": [{"stat": str, "value": float}, ...],
      "negatives": [{"stat": str, "value": float}, ...],
      "raw_lines": [str, ...]
    }

    Deduplication: Warframe cannot roll the same stat twice.  If OCR reads
    the same canonical stat name more than once (e.g. two "Critical Chance"
    lines from reading both the left and right card), we keep only the FIRST
    occurrence.  This prevents phantom extra "hits" inflating the score.

    Sanity limits: riven stat values outside realistic Warframe ranges are
    treated as OCR garbage and dropped:
      Positives: 0 < value ≤ 999%
      Negatives: 0 < |value| ≤ 999%
    Values like +2226% CC or -1445% CC are impossible and signal a misread.
    """
    return parse_result(ocr_lines).to_legacy()


def format_stats(parsed: ParsedRollDict | dict) -> str:
    """Human-readable one-line summary of a parsed roll."""
    parts = []
    for s in parsed.get("positives", []):
        parts.append(f"+{s['value']:.1f}% {s['stat']}")
    for s in parsed.get("negatives", []):
        parts.append(f"{s['value']:.1f}% {s['stat']}")
    return " | ".join(parts) if parts else "(no stats detected)"
