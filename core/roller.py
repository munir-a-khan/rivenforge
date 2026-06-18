"""
Main rolling loop — runs in a background thread.

Strategy: Keep rolling on the best roll seen so far.
  - After each roll, score it: profile hit fraction * 1000 + RAG * 10 - neg penalty
  - If new roll scores HIGHER than current best → keep it (click YES after CONFIRM)
  - If new roll scores LOWER or equal        → revert (click NO after CONFIRM)
  - If new roll is a FULL profile match      → keep it and stop

This means the riven always ratchets upward — we never go back to a worse roll.
"""

import threading
import time
from typing import Callable


class RollerThread(threading.Thread):
    def __init__(
        self,
        weapon: str,
        weapon_type: str,
        profiles: list,
        roll_limit: int = 100,
        rag_threshold: float = 0.6,
        animation_wait: float = 2.5,
        on_roll: Callable | None = None,
        on_done: Callable | None = None,
        on_error: Callable | None = None,
    ):
        super().__init__(daemon=True)
        self.weapon         = weapon
        self.weapon_type    = weapon_type
        self.profiles       = profiles
        self.roll_limit     = roll_limit
        self.rag_threshold  = rag_threshold
        self.animation_wait = animation_wait
        self.on_roll        = on_roll
        self.on_done        = on_done
        self.on_error       = on_error
        self._stop_flag     = threading.Event()

    def stop(self):
        self._stop_flag.set()

    def run(self):
        from core import parser, rules, automation
        from core import roll_logger as rlog
        from core.automation import _find_on_screen
        from core.capture import grab_frame
        from core.vision  import find_riven_stats, reset_persistence_blacklist
        from rag import rag as rag_mod

        reset_persistence_blacklist()   # clear left-card bleed history from prior session

        sf         = self._stop_flag
        roll_num   = 0
        kuva_spent = 0

        rlog.log_session_start(self.weapon, self.weapon_type, self.profiles)

        # Track best roll seen so far (score + summary for display).
        # Start at -9999 so any valid readable roll beats "nothing".
        # score_roll() returns -9999 for unreadable rolls, so they
        # never become the best even on roll #1.
        best_score   = -9999.0
        best_summary = "none"

        try:
            while not sf.is_set():
                if self.roll_limit > 0 and roll_num >= self.roll_limit:
                    self._finish(
                        f"Roll limit reached ({self.roll_limit}) | "
                        f"Best roll: {best_summary} | "
                        f"Kuva spent: ~{kuva_spent:,}"
                    )
                    return

                roll_num   += 1
                roll_cost   = min(900 + (roll_num - 1) * 100, 3500)
                kuva_spent += roll_cost

                # ── 1. Click CYCLE FOR KUVA ───────────────────────────────────
                if automation.press_cycle(sf): break

                # ── 2. Click YES on "Are you sure?" ──────────────────────────
                if automation.wait_for_dialog(0.6, sf): break
                if automation.click_cycle_yes(sf): break

                # ── 3. Wait for roll animation, then for CONFIRM to appear ────
                # First do the minimum animation wait (configurable, default 2.5s)
                if automation.wait_for_animation(self.animation_wait, sf): break

                # Then poll until CONFIRM button is visible — means two-card
                # view is fully rendered and stats are readable
                _confirm_visible = False
                _poll_deadline   = time.monotonic() + 8.0
                while time.monotonic() < _poll_deadline:
                    if sf.is_set(): break
                    if _find_on_screen("CONFIRM"):
                        _confirm_visible = True
                        break
                    time.sleep(0.4)
                if sf.is_set(): break

                # Small extra pause to let the card text fully settle after
                # CONFIRM appears (prevents partial OCR reads)
                if automation.wait_for_dialog(0.4, sf): break

                # ── 4. OCR the new card (right side in two-card view) ─────────
                frame      = grab_frame()
                stat_lines = find_riven_stats(frame)
                parsed     = parser.parse(stat_lines)

                # Retry up to 2 more times if stats are missing
                _retry = 0
                while _retry < 2 and not parsed["positives"] and not parsed["negatives"]:
                    if automation.wait_for_dialog(0.7, sf): break
                    frame      = grab_frame()
                    stat_lines = find_riven_stats(frame)
                    parsed     = parser.parse(stat_lines)
                    _retry    += 1
                if sf.is_set(): break

                # Black-frame detection: both the GDI/BitBlt path AND the
                # DXGI Desktop Duplication fallback returned black. That
                # generally means the dxcam dependency isn't installed OR
                # Warframe is on a monitor dxcam can't enumerate.
                # Either way, burning kuva on un-readable rolls is pointless.
                if frame.info.get("black_frame") and not parsed["positives"] and not parsed["negatives"]:
                    path = frame.info.get("capture_path", "unknown")
                    self._finish(
                        f"STOPPED: capture returned a black frame "
                        f"(brightness {frame.info.get('brightness', 0)}, path={path}). "
                        "Try: switch Warframe to Borderless Windowed, "
                        "or install dxcam (pip install dxcam) and retry."
                    )
                    return

                # ── 5. Evaluate ───────────────────────────────────────────────
                rule_result = rules.evaluate(parsed, self.profiles)

                rag_result = {"score": 0.0, "notes": [], "weapon_data": None}
                if parsed["positives"]:   # only query RAG if we got stats
                    rag_result = rag_mod.score(parsed, self.weapon, self.weapon_type)

                rag_score = rag_result.get("score", 0.0)

                # Full accept: profile matched + RAG threshold met
                full_accept = (
                    rule_result["accept"]
                    and (self.rag_threshold == 0.0 or rag_score >= self.rag_threshold)
                )

                # If OCR got nothing at all — treat as bad roll, always revert
                ocr_failed = not parsed["positives"] and not parsed["negatives"]

                # Score for "is this roll better than what we have?"
                # score_roll() returns -9999 for unreadable rolls, so they
                # can never beat best_score (which starts at -9999 and only
                # rises when we keep a readable roll). ocr_failed is still
                # kept as an extra guard for full_accept gating.
                melee_bonus = rag_result.get("melee_bonus", 0.0)
                new_score   = rules.score_roll(parsed, self.profiles,
                                               rag_score, melee_bonus)
                # Safety: market/RAG score may rank acceptable rolls, but it
                # must never cause us to keep a roll that failed user rules.
                is_better   = (
                    (not ocr_failed)
                    and rule_result["accept"]
                    and (new_score > best_score)
                )

                rag_result["kuva_cost"]   = roll_cost
                rag_result["kuva_total"]  = kuva_spent
                # Pass WFM price fields through for roll log display
                rag_result.setdefault("plat_low",    None)
                rag_result.setdefault("plat_median",  None)
                rag_result.setdefault("wfm_source",   "none")
                rag_result.setdefault("melee_bonus",   0.0)
                rag_result["new_score"]   = round(new_score, 2)
                rag_result["best_score"]  = round(best_score, 2)
                rag_result["is_better"]   = is_better

                if self.on_roll:
                    self.on_roll(roll_num, parsed, rule_result, rag_result,
                                 full_accept)

                # ── Debug file log ────────────────────────────────────────────
                if full_accept and not ocr_failed:
                    _decision_str = "ACCEPTED"
                elif is_better:
                    _decision_str = "NEW BEST"
                else:
                    _decision_str = "REVERT"
                try:
                    from core.vision import _blacklisted_lines
                    capture_info = dict(frame.info or {})
                    capture_info["frame_size"] = frame.size
                    rlog.log_roll(
                        roll_num      = roll_num,
                        kuva_cost     = roll_cost,
                        kuva_total    = kuva_spent,
                        raw_lines     = parsed.get("raw_lines", []),
                        parsed        = parsed,
                        rule_result   = rule_result,
                        rag_result    = rag_result,
                        new_score     = new_score,
                        best_score    = best_score,
                        decision      = _decision_str,
                        dropped_dupes     = parsed.get("dropped_dupes",  []),
                        dropped_sanity    = parsed.get("dropped_sanity", []),
                        blacklisted_lines = list(_blacklisted_lines),
                        capture_info      = capture_info,
                    )
                except Exception:
                    pass   # never let logging crash the rolling loop

                # ── 6. Keep or revert ─────────────────────────────────────────
                #
                # KEEP path (full_accept or is_better):
                #   click CONFIRM → YES/NO dialog → click YES → CYCLE FOR
                #
                # REVERT path (worse/equal/ocr_failed):
                #   revert_roll() handles the full sequence:
                #   click CONFIRM → YES/NO → click NO → left card selected
                #   → YES/NO again → click YES → CYCLE FOR

                if full_accept and not ocr_failed:
                    # Perfect roll — keep and stop
                    if automation.click_confirm(sf): break
                    if automation.wait_for_dialog(0.5, sf): break
                    automation.click_keep_yes(sf)
                    self._finish(
                        f"ACCEPTED roll #{roll_num} | "
                        f"Profile: {rule_result.get('profile_matched','?')} | "
                        f"RAG: {rag_score:.2f} | "
                        f"Kuva: ~{kuva_spent:,}"
                    )
                    return

                elif is_better:
                    # Better than current — keep it, keep rolling
                    if automation.click_confirm(sf): break
                    if automation.wait_for_dialog(0.5, sf): break
                    if automation.click_keep_yes(sf): break
                    best_score   = new_score
                    best_summary = parser.format_stats(parsed)
                    if automation.wait_for_screen_settle(sf): break

                else:
                    # Worse, equal, or OCR failed — full revert sequence:
                    # CONFIRM → NO → YES (confirm old riven)
                    if automation.revert_roll(sf): break

            if sf.is_set():
                self._finish(
                    f"Stopped after {roll_num} roll(s) | "
                    f"Best: {best_summary} | "
                    f"Kuva: ~{kuva_spent:,}"
                )

        except Exception as e:
            import traceback
            if self.on_error:
                self.on_error(f"{e}\n{traceback.format_exc()}")

    def _finish(self, reason: str):
        try:
            from core import roll_logger as rlog
            rlog.log_session_end(reason)
        except Exception:
            pass
        if self.on_done:
            self.on_done(reason)
