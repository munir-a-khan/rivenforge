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


# The persistence blacklist is DISABLED.
#
# It assumed "a stat line seen across several rolls = the static left/equipped
# card bleeding into the crop." That premise breaks the moment the roller
# ratchets to a good roll: that roll becomes the left card, so its stats
# legitimately recur — and a NEW roll that shares any of those stats gets them
# silently suppressed. In the field this reverted a genuinely-good roll
# (Fire Rate + Damage + Status Chance) down to "(none)" because Fire Rate and
# Damage had been blacklisted from an earlier best. It was also poisoned
# mid-roll by the triple-check re-reads.
#
# Left-card bleed is now handled by mechanisms that can't suppress a real
# stat: the right-side crop below isolates the new card, the physical-limit
# guard rejects any read with more than 3 positives / 1 negative (a bled
# read), and triple-check consensus requires several reads to agree before
# acting. None of those can silently delete a legitimate rolled stat.
_BLACKLIST_ENABLED = False


def _update_persistence_blacklist(new_lines: list[str]):
    """No-op while the blacklist is disabled (see note above)."""
    if not _BLACKLIST_ENABLED:
        return
    global _blacklisted_lines
    _recent_lines.append(set(new_lines))
    if len(_recent_lines) < 3:
        return
    from collections import Counter
    freq: Counter = Counter()
    for roll_set in _recent_lines:
        for line in roll_set:
            freq[line] += 1
    for line, count in freq.items():
        if count >= 3 and line not in _blacklisted_lines:
            _blacklisted_lines.add(line)


# ── New-card identification by "the equipped card is static" ────────────────
#
# In the two-card cycle-compare view, the CURRENTLY-EQUIPPED riven and the
# freshly-ROLLED riven sit side by side. The equipped card's stats are
# IDENTICAL on every roll; the new card's stats change each roll. We exploit
# exactly that: cluster the OCR into left/right columns by x-position, learn
# which column signature stays constant across rolls (= equipped), and keep the
# OTHER column (= the new roll). This is geometry-agnostic — it doesn't matter
# which physical side the new card is on — and it can't suppress a legitimate
# stat the way the old persistence blacklist did.
# NOTE ON THE OLD COLUMN-CLUSTERING APPROACH (removed):
# We previously OCR'd the full card band and clustered items into left/right
# columns, learning which column was the static equipped card. A live field
# failure killed it: the two compare cards sit close enough that winocr merges
# text from BOTH cards into single lines (e.g. the old card's "Status Chance"
# fused with the new card's name), producing one mid-point column that mixes
# old and new stats — stable enough that consensus re-reads "agreed" on the
# contaminated result. The fix is physical, not statistical: crop tightly to
# the SELECTED (centre, brightened) card so the old card is never in frame.
_last_cluster_debug: str = ""   # human-readable read info for the roll log
_last_riven_name: str = ""      # raw card name text from the last read (weapon + grammar)


def last_riven_name() -> str:
    """The riven card NAME captured on the most recent find_riven_stats read."""
    return _last_riven_name


def reset_persistence_blacklist():
    """Call at session start to clear per-session read state."""
    global _blacklisted_lines, _last_riven_name
    _recent_lines.clear()
    _blacklisted_lines.clear()
    _last_riven_name = ""


def _find_confirm_cx(img: Image.Image) -> float | None:
    """
    Locate the CONFIRM button's x-centre by OCRing a thin strip across its row.
    The selected (new) card is always centred directly above CONFIRM, so this
    anchors the card crop even when the compare view shifts left/right. Returns
    None when CONFIRM isn't visible (single-card cycle screen).
    """
    w, h = img.size
    strip = img.crop((0, int(h * 0.74), w, int(h * 0.88)))
    for it in _ocr_screen(strip):
        if "confirm" in it["text"].lower():
            return it["cx"]
    return None


def _looks_like_name_part(text: str) -> bool:
    """A riven name row: capitalised word(s), no digits, not UI chrome."""
    t = text.strip()
    if not t or any(c.isdigit() for c in t):
        return False
    lower = t.lower()
    if any(s in lower for s in ("mr ", "fits in", "confirm", "cycle", "kuva",
                                "show", "close", "veiled", "remaining")):
        return False
    return sum(c.isalpha() for c in t) >= 3


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

    # Reject known UI strings even if they contain numbers.
    # NOTE: "capacity" must NOT be in this list — "+65.9% Magazine Capacity"
    # is a real riven stat and was being silently dropped (found live on a
    # Drakgoon riven). The mod-drain UI element is covered by "fits in", and
    # everything here already requires a digit plus a sign/% to qualify.
    lower = t.lower()
    skip = ("kuva", "cycle", "confirm", "remaining", "mastery", "rank",
            "mr ", "mod ", "veiled", "close", "show", "initial combo",
            "riven mod", "fits in")
    if any(s in lower for s in skip):
        return False

    # Must have at least 2 non-digit non-symbol chars (the stat name)
    letters = sum(1 for c in t if c.isalpha())
    if letters < 2:
        return False

    return True


def find_riven_stats(img: Image.Image) -> list[str]:
    """
    Extract the NEW (just-rolled) riven card's stat lines.

    The two-card cycle-compare view shows the equipped riven beside the new
    roll. Rather than assume a fixed left/right crop (which mis-fires when the
    layout shifts and truncates the new card at the 4-stat cap), we OCR the
    whole card band, cluster into x-position columns, and keep the column that
    is NOT the learned equipped card. When only one card is on screen (single
    card view between rolls) there's one column and we take it.

    Learning happens in ``note_roll_complete`` (called once per roll), so the
    equipped signature is derived from cross-roll history and is stable across
    the within-roll consensus re-reads.
    """
    global _last_cluster_debug

    w, h = img.size

    # The SELECTED (new) card is not at a fixed x — the whole compare view can
    # shift left/right between rolls, so a fixed centre crop misses it (dropping
    # the name + top stat). Instead we ANCHOR on the CONFIRM button, which always
    # sits directly beneath the selected card. We find CONFIRM's x, then crop a
    # single-card-wide column centred on it, above the button. This isolates the
    # selected card wherever it is, and excludes the dimmed old card so winocr
    # can't merge the two cards' rows.
    cx = _find_confirm_cx(img)
    if cx is None:
        cx = w * 0.50   # single-card view (cycle screen): card is centred
    x0 = int(max(0, cx - w * 0.105))
    x1 = int(min(w, cx + w * 0.105))
    y0, y1 = int(h * 0.44), int(h * 0.80)
    crop = img.crop((x0, y0, x1, y1))

    ordered = [
        _normalise_signs(it["text"].strip())
        for it in sorted(_ocr_screen(crop), key=lambda i: i["cy"])
        if it["text"].strip()
    ]

    from core.parser import merge_wrapped_stat_lines

    global _last_riven_name
    # The card NAME (weapon + grammar) sits above the stats, so the leading
    # non-stat rows are the name — capture them before the first stat line so
    # the roller can decode the positives from the name (far more reliable OCR
    # than the small stat rows).
    name_parts: list[str] = []
    stats: list[str] = []
    seen: set[str] = set()
    merged = merge_wrapped_stat_lines(ordered)
    for t in merged:
        if _is_stat_line(t):
            if len(stats) >= 4:  # Warframe hard limit: 3 positives + 1 negative
                continue
            if t not in seen:
                seen.add(t)
                stats.append(t)
        elif not stats and _looks_like_name_part(t):
            name_parts.append(t)
    _last_riven_name = " ".join(name_parts).strip()

    _last_cluster_debug = f"center-card {len(stats)}st name='{_last_riven_name}'"
    return stats
