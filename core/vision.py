"""
Visual button detection for Warframe riven rolling.

Instead of fixed calibrated coordinates, we OCR the game screen to find
button text labels and return their center positions dynamically.

This means zero calibration required — works at any resolution,
any UI scale, even if Warframe moves its UI elements.

Buttons are found by searching for their text in the OCR output:
  "CYCLE FOR"   -> CYCLE FOR KUVA button
  "YES" (lower) -> YES on "Are you sure?" dialog  (y > screen_h * 0.5)
  "NO"          -> NO on "Are you sure?" dialog
  "CONFIRM"     -> CONFIRM button (two-card view)
  "YES" (upper) -> YES on "Cycle Riven?" dialog   (y < screen_h * 0.5)
  "NO"  (upper) -> NO on "Cycle Riven?" dialog
"""

import time
import collections
from PIL import Image

from core.contracts import ButtonPositionsDict

# ── Persistent-line blacklist ─────────────────────────────────────────────────
# Tracks raw OCR stat lines across recent rolls.  Any line that appears in
# 3 or more of the last 4 rolls is almost certainly the LEFT card bleeding
# into the crop — it's a static stat from the currently-equipped riven.
# We blacklist it for the session so it never contaminates the new roll read.
_recent_lines: collections.deque = collections.deque(maxlen=4)   # last 4 roll line-sets
_blacklisted_lines: set = set()   # lines confirmed as left-card bleed


def _update_persistence_blacklist(new_lines: list[str]):
    """
    Called after each roll with the raw stat lines found.
    Updates the rolling history and adds any line seen in ≥3 of last 4 rolls
    to the session blacklist.
    """
    global _blacklisted_lines
    _recent_lines.append(set(new_lines))

    if len(_recent_lines) < 3:
        return   # not enough history yet

    # Count how many rolls each line appeared in
    from collections import Counter
    freq: Counter = Counter()
    for roll_set in _recent_lines:
        for line in roll_set:
            freq[line] += 1

    for line, count in freq.items():
        if count >= 3 and line not in _blacklisted_lines:
            _blacklisted_lines.add(line)


def reset_persistence_blacklist():
    """Call at session start to clear cross-session bleed."""
    global _blacklisted_lines
    _recent_lines.clear()
    _blacklisted_lines.clear()


def _ocr_screen(img: Image.Image) -> list[dict]:
    """
    Run winocr on img, return list of dicts:
    { text, cx, cy, x, y, w, h }
    """
    import winocr
    result = winocr.recognize_pil_sync(img, "en")
    items = []
    for line in result.get("lines", []):
        text = line.get("text", "").strip()
        words = line.get("words", [])
        if not text or not words:
            continue
        # Build bounding box from all words in line
        xs = [w["bounding_rect"]["x"] for w in words if "bounding_rect" in w]
        ys = [w["bounding_rect"]["y"] for w in words if "bounding_rect" in w]
        ws = [w["bounding_rect"]["width"]  for w in words if "bounding_rect" in w]
        hs = [w["bounding_rect"]["height"] for w in words if "bounding_rect" in w]
        if not xs:
            continue
        x = min(xs)
        y = min(ys)
        x2 = max(x2 + w2 for x2, w2 in zip(xs, ws))
        y2 = max(y2 + h2 for y2, h2 in zip(ys, hs))
        items.append({
            "text": text,
            "x": x, "y": y,
            "w": x2 - x, "h": y2 - y,
            "cx": (x + x2) / 2,
            "cy": (y + y2) / 2,
        })
    return items


def _find_text(items: list[dict], keyword: str,
               y_min: float = 0, y_max: float = 99999,
               x_min: float = 0, x_max: float = 99999,
               ) -> dict | None:
    """
    Find first OCR item whose text contains keyword (case-insensitive)
    within optional screen region constraints.
    """
    kw = keyword.lower()
    for item in items:
        if kw in item["text"].lower():
            if y_min <= item["cy"] <= y_max and x_min <= item["cx"] <= x_max:
                return item
    return None


def find_all_buttons(img: Image.Image) -> ButtonPositionsDict:
    """
    Scan img for all riven rolling UI buttons.
    Returns dict of button_name -> (cx, cy) or None if not found.

    Screen is divided into regions based on what's expected:
      cycle_button   : anywhere, text "CYCLE FOR"
      cycle_yes      : bottom half, text "YES"  (confirm kuva dialog)
      cycle_no       : bottom half, text "NO"
      confirm_button : anywhere, text "CONFIRM"
      keep_yes       : anywhere after CONFIRM pressed, text "YES"
      keep_no        : anywhere after CONFIRM pressed, text "NO"
    """
    w, h = img.size
    items = _ocr_screen(img)

    def _pos(item):
        return (int(item["cx"]), int(item["cy"])) if item else None

    # Cycle button: "CYCLE FOR" text
    cycle = _find_text(items, "CYCLE FOR")

    # YES/NO buttons: there can be two YES/NO pairs at different y positions
    # Collect all YES and NO occurrences
    yes_hits = [i for i in items if i["text"].strip().upper() in ("YES", "YES.")]
    no_hits  = [i for i in items if i["text"].strip().upper() in ("NO",  "NO.")]

    # Sort by y
    yes_hits.sort(key=lambda i: i["cy"])
    no_hits.sort(key=lambda i: i["cy"])

    # The "Are you sure?" dialog YES/NO is in the lower portion of the screen
    # The "Cycle Riven into current selection?" YES/NO is typically in upper-middle
    # In practice Warframe shows one dialog at a time, so just use whichever YES/NO is visible
    yes1 = yes_hits[0] if yes_hits else None      # first YES found
    no1  = no_hits[0]  if no_hits  else None      # first NO found

    # CONFIRM button
    confirm = _find_text(items, "CONFIRM")

    return {
        "cycle_button":   _pos(cycle),
        "cycle_yes":      _pos(yes1),
        "cycle_no":       _pos(no1),
        "confirm_button": _pos(confirm),
        "keep_yes":       _pos(yes1),
        "keep_no":        _pos(no1),
        "_all_text":      [(i["text"], int(i["cx"]), int(i["cy"])) for i in items],
    }


def _normalise_signs(text: str) -> str:
    """
    Replace Unicode minus/dash variants with ASCII hyphen-minus.
    winocr sometimes returns U+2212 (−), U+2013 (–), U+2014 (—) for
    the leading sign on a negative riven stat.
    Also normalise U+FF0B (＋) to ASCII +.
    """
    return (
        text
        .replace("\u2212", "-")   # Unicode MINUS SIGN
        .replace("\u2013", "-")   # EN DASH
        .replace("\u2014", "-")   # EM DASH
        .replace("\uff0b", "+")   # FULLWIDTH PLUS
        .replace("\uff0d", "-")   # FULLWIDTH HYPHEN-MINUS
    )


def _is_stat_line(text: str) -> bool:
    """
    Return True if this OCR line looks like a riven stat.
    Must have a number AND a % sign OR a +/- prefix.
    Must NOT be pure UI text.
    """
    t = _normalise_signs(text.strip())
    has_digit   = any(c.isdigit() for c in t)
    has_percent = "%" in t
    # Accept both ASCII +/- and Unicode variants (after normalisation above)
    has_sign    = t.startswith("+") or t.startswith("-")

    if not has_digit:
        return False
    if not (has_percent or has_sign):
        return False

    # Reject known UI strings even if they contain numbers
    lower = t.lower()
    skip = ("kuva", "cycle", "confirm", "remaining", "mastery", "rank",
            "mr ", "mod ", "veiled", "close", "show", "initial combo",
            "riven mod", "fits in", "capacity")
    if any(s in lower for s in skip):
        return False

    # Must have at least 2 non-digit non-symbol chars (the stat name)
    letters = sum(1 for c in t if c.isalpha())
    if letters < 2:
        return False

    return True


def find_riven_stats(img: Image.Image) -> list[str]:
    """
    Extract stat lines from the NEW riven card only (right side of screen).

    Two-card comparison layout in Warframe:
      Left  card  ≈  x 5%–48%   (OLD / currently equipped riven)
      Right card  ≈  x 52%–95%  (NEW roll — what we want to read)

    The left card bleeds into a 52% crop, so we use 67% as the primary
    right-card start.  The fallback regions are for single-card mode
    (after accept/revert before the next roll begins).

    Warframe riven max stats: 3 positives + 1 negative = 4 lines total.
    We hard-cap at 4 to avoid OCR noise lines being included.
    """
    w, h = img.size
    seen  = set()
    stats = []

    MAX_STATS = 4   # Warframe hard limit: 3 pos + 1 neg

    def _collect(crop_box):
        cropped = img.crop(crop_box)
        items   = _ocr_screen(cropped)
        # Collect in OCR reading order, dropping known left-card bleed.
        # The Warframe UI wraps long stat names like "Critical Chance for
        # Slide Attack" onto a second display line, which winocr returns as
        # a separate item — merge_wrapped_stat_lines stitches them back into
        # one stat line so the parser can resolve the full name.
        ordered = [
            _normalise_signs(item["text"].strip())
            for item in items
            if item["text"].strip()
        ]
        ordered = [t for t in ordered if t not in _blacklisted_lines]
        from core.parser import merge_wrapped_stat_lines
        for t in merge_wrapped_stat_lines(ordered):
            if len(stats) >= MAX_STATS:
                break
            if _is_stat_line(t) and t not in seen:
                seen.add(t)
                stats.append(t)

    top    = int(h * 0.20)
    bottom = int(h * 0.85)

    # Region 1: far-right crop — strictly the new card, avoids left card bleed
    # x: 67%–100% covers the right card without touching the left card at ~35–48%
    _collect((int(w * 0.67), top, w, bottom))

    # Region 2: slightly wider right — catches text near the card's left edge
    # x: 58%–100%, only if we got fewer than 2 stats from the tight crop
    if len(stats) < 2:
        _collect((int(w * 0.58), top, w, bottom))

    # Region 3: single-card fallback — used when Warframe shows one card only
    # (e.g. right after cycling before comparison appears)
    # x: 30%–70% — centre of screen, excludes far left and far right noise
    if len(stats) < 2:
        _collect((int(w * 0.30), top, int(w * 0.70), bottom))

    # Update persistence blacklist with the lines found this roll
    _update_persistence_blacklist(stats)

    return stats
