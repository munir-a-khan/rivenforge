"""
Debug file logger for every roll cycle.

Writes a plain-text log to logs/roll_debug.log so you can see exactly
what the tool detected, parsed, and decided for every roll — even when
the GUI log is truncated or scrolled off.

Format per roll:
─────────────────────────────────────────────────────────────────
[2024-01-15 14:32:01] ROLL #5  (kuva: 1,300  total: 5,800)
  RAW OCR lines:
    "+878.0% Finisher Damage"
    "+50.3% Attack Speed"
    "+818.0% Electricity"
  PARSED positives:
    Finisher Damage    +878.0%
    Attack Speed       +50.3%
    Electricity        +818.0%
  PARSED negatives:
    (none)
  DEDUPLICATION dropped: (none)
  SANITY dropped (value > 999): (none)
  SCORE:  new=205  best_so_far=-9999  → REVERT
  PROFILE eval: No profile matched. Best: 'Melee' with 0 hit(s).
  RAG score: 0.312  plat_low=None  plat_median=None  melee_bonus=+0.06
─────────────────────────────────────────────────────────────────
"""

import os
import time
import threading
from datetime import datetime

_LOG_DIR  = os.path.join(os.path.dirname(__file__), "..", "logs")
_LOG_PATH = os.path.join(_LOG_DIR, "roll_debug.log")
_MAX_BYTES = 10 * 1024 * 1024   # 10 MB — rotate when exceeded

_lock = threading.Lock()
_fh   = None   # file handle, opened lazily


def _open_log():
    global _fh
    os.makedirs(_LOG_DIR, exist_ok=True)
    # Rotate if too big
    if os.path.exists(_LOG_PATH) and os.path.getsize(_LOG_PATH) > _MAX_BYTES:
        rotated = _LOG_PATH + ".old"
        if os.path.exists(rotated):
            os.remove(rotated)
        os.rename(_LOG_PATH, rotated)
    _fh = open(_LOG_PATH, "a", encoding="utf-8", buffering=1)   # line-buffered


def _write(text: str):
    global _fh
    with _lock:
        if _fh is None or _fh.closed:
            _open_log()
        _fh.write(text)
        _fh.flush()


def log_session_start(weapon: str, weapon_type: str, profiles: list):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"\n{'='*70}\n",
        f"SESSION START  {ts}\n",
        f"  Weapon     : {weapon} ({weapon_type or 'unknown type'})\n",
        f"  Profiles   : {len(profiles)}\n",
    ]
    for i, p in enumerate(profiles, 1):
        lines.append(
            f"    [{i}] {p.get('name','?')}  "
            f"want={p.get('desired_positives',[])}  "
            f"min={p.get('min_positives_required',2)}  "
            f"ok_neg={p.get('acceptable_negatives',[])}\n"
        )
    lines.append(f"{'='*70}\n")
    _write("".join(lines))


def log_roll(
    roll_num:    int,
    kuva_cost:   int,
    kuva_total:  int,
    raw_lines:   list[str],
    parsed:      dict,
    rule_result: dict,
    rag_result:  dict,
    new_score:   float,
    best_score:  float,
    decision:    str,          # "REVERT" | "NEW BEST" | "ACCEPTED"
    dropped_dupes:     list[str] = None,
    dropped_sanity:    list[str] = None,
    blacklisted_lines: list[str] = None,
    capture_info:      dict      = None,   # frame.info from grab_frame
):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep = "─" * 70

    positives = parsed.get("positives", [])
    negatives = parsed.get("negatives", [])
    rag_score    = rag_result.get("score",       0.0)
    plat_low     = rag_result.get("plat_low",    None)
    plat_median  = rag_result.get("plat_median", None)
    melee_bonus  = rag_result.get("melee_bonus", 0.0)
    rag_notes    = rag_result.get("notes",       [])

    lines = [
        f"\n[{ts}] ROLL #{roll_num}  "
        f"(kuva: {kuva_cost:,}  total: {kuva_total:,})\n",
    ]

    # Capture diagnostics — which path got us pixels, was the frame dark,
    # what dimensions. Critical for postmortem when a god roll gets missed:
    # tells you immediately whether to blame capture, OCR, or parser.
    if capture_info:
        path = capture_info.get("capture_path", "?")
        brightness = capture_info.get("brightness", "?")
        size = capture_info.get("frame_size")
        size_str = f"{size[0]}x{size[1]}" if isinstance(size, tuple) else "?"
        black = " [DARK]" if capture_info.get("black_frame") else ""
        lines.append(
            f"  CAPTURE: path={path}  brightness={brightness}  "
            f"size={size_str}{black}\n"
        )

    # Raw OCR
    lines.append("  RAW OCR lines:\n")
    if raw_lines:
        for r in raw_lines:
            lines.append(f"    {repr(r)}\n")
    else:
        lines.append("    (none)\n")

    # Dropped by sanity check
    if dropped_sanity:
        lines.append("  SANITY DROPPED (value > 999 or ≤ 0):\n")
        for d in dropped_sanity:
            lines.append(f"    {d}\n")

    # Dropped by deduplication
    if dropped_dupes:
        lines.append("  DEDUPLICATION DROPPED (same stat seen twice):\n")
        for d in dropped_dupes:
            lines.append(f"    {d}\n")

    # Active left-card bleed blacklist (lines suppressed from vision.py)
    if blacklisted_lines:
        lines.append("  BLACKLISTED (left-card bleed, suppressed by persistence filter):\n")
        for b in sorted(blacklisted_lines):
            lines.append(f"    {b}\n")

    # Parsed positives
    lines.append("  PARSED positives:\n")
    if positives:
        for s in positives:
            lines.append(f"    {s['stat']:<35} +{s['value']:.1f}%\n")
    else:
        lines.append("    (none)\n")

    # Parsed negatives
    lines.append("  PARSED negatives:\n")
    if negatives:
        for s in negatives:
            lines.append(f"    {s['stat']:<35} {s['value']:.1f}%\n")
    else:
        lines.append("    (none)\n")

    # Score + decision
    arrow = "→"
    lines.append(
        f"  SCORE:  new={new_score:.1f}  best_so_far={best_score:.1f}  "
        f"{arrow} {decision}\n"
    )

    # Profile evaluation
    lines.append(f"  PROFILE: {rule_result.get('details','?')}\n")

    # RAG + WFM
    plat_str = f"{plat_low}p / {plat_median}p" if plat_median else "no data"
    lines.append(
        f"  RAG={rag_score:.3f}  plat={plat_str}  "
        f"melee_bonus={melee_bonus:+.2f}\n"
    )
    for note in rag_notes:
        lines.append(f"    note: {note}\n")

    lines.append(f"  {sep}\n")
    _write("".join(lines))


def log_session_end(reason: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _write(
        f"\n[{ts}] SESSION END: {reason}\n"
        f"{'='*70}\n"
    )


def close():
    global _fh
    with _lock:
        if _fh and not _fh.closed:
            _fh.close()
            _fh = None
