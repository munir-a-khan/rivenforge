"""
Main rolling loop — runs in a background thread.

Strategy: Keep rolling on the best roll seen so far.
  - After each roll, score it: profile hit fraction * 1000 + RAG * 10 - neg penalty
  - If new roll scores HIGHER than current best → keep it (click YES after CONFIRM)
  - If new roll scores LOWER or equal        → revert (click NO after CONFIRM)
  - If new roll is a FULL profile match      → keep it and stop

This means the riven always ratchets upward — we never go back to a worse roll.

Resilience: a single mid-roll UI hiccup (a button that OCR-timed-out, a dropped
capture frame, a focus flicker) is NOT fatal. Historically any such error raised
straight out of the loop and killed the whole session — "rolls fine for a while
then stops out of nowhere." Now each roll runs under a guard that catches the
hiccup, recovers to a cycle-ready screen, and keeps going; only CONSECUTIVE
failures (Warframe closed / left the riven screen) end the session, with a clear
reason.
"""

import threading
import time
from typing import Callable

# How many roll attempts may fail back-to-back before we conclude something is
# genuinely wrong (game closed, no longer on the riven screen) and stop. A
# single flaky OCR read costs one retry, never the session.
MAX_CONSECUTIVE_HICCUPS = 6


class RollerThread(threading.Thread):
    def __init__(
        self,
        weapon: str,
        weapon_type: str,
        profiles: list,
        roll_limit: int = 100,
        rag_threshold: float = 0.6,
        animation_wait: float = 2.5,
        stat_priority: list | None = None,
        neg_priority: list | None = None,
        roll_until_match: bool = False,
        confirm_reads: int = 3,
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
        # Per-weapon manual stat preference order (highest first). Biases the
        # keep/revert score toward the user's favoured stat combination.
        self.stat_priority  = list(stat_priority or [])
        # Per-weapon NEGATIVE preference order (most-tolerable first). Among
        # rolls whose negative is already acceptable, biases toward the one
        # with the least-bad negative (or no negative at all).
        self.neg_priority   = list(neg_priority or [])
        # roll_until_match: when True, only KEEP a roll that FULLY matches a
        # profile; every other roll is reverted (no "ratchet to best-so-far").
        self.roll_until_match = roll_until_match
        # confirm_reads: how many OCR reads of the SAME rolled card must agree
        # before we trust the read for a keep/revert decision. Re-reading is
        # free (no kuva spent), so this is a cheap correctness guard. 1 = off.
        self.confirm_reads = max(1, int(confirm_reads))
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

        # Consecutive-failure guard (see MAX_CONSECUTIVE_HICCUPS). Reset to 0
        # after every clean roll so only a genuine run of failures stops us.
        consecutive_hiccups = 0
        last_hiccup         = ""

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

                # ── One guarded roll attempt ─────────────────────────────────
                # Everything a single roll touches the game UI for lives inside
                # this try. A transient failure (button not found in time, a
                # dropped frame) is recovered from instead of ending the run.
                try:
                    # ── 1. Click CYCLE FOR KUVA ───────────────────────────────
                    if automation.press_cycle(sf): break

                    # ── 2. Click YES on "Are you sure?" ──────────────────────
                    if automation.wait_for_dialog(0.6, sf): break
                    if automation.click_cycle_yes(sf): break

                    # ── 3. Wait for roll animation, then for CONFIRM to appear ─
                    # First do the minimum animation wait (configurable, default 2.5s)
                    if automation.wait_for_animation(self.animation_wait, sf): break

                    # Then poll until CONFIRM button is visible — means two-card
                    # view is fully rendered and stats are readable. Poll quickly
                    # (0.15s) so we react the instant the card appears rather than
                    # sitting through a fixed wait — this is the main per-roll
                    # latency win and is safe (it only reads sooner, never earlier
                    # than the button actually exists).
                    _confirm_visible = False
                    _poll_deadline   = time.monotonic() + 8.0
                    while time.monotonic() < _poll_deadline:
                        if sf.is_set(): break
                        if _find_on_screen("CONFIRM"):
                            _confirm_visible = True
                            break
                        time.sleep(0.15)
                    if sf.is_set(): break

                    # Small extra pause to let the card text fully settle after
                    # CONFIRM appears (prevents partial OCR reads)
                    if automation.wait_for_dialog(0.4, sf): break

                    # ── 4. OCR the new card — triple-check consensus ─────────
                    # Read the Warframe *window* via WGC, not a screen region: an
                    # overlay on top (tooltip, the rivenforge window itself) won't
                    # corrupt the read, and it targets the right window explicitly.
                    # WGC falls back to the mss/DXGI ladder when unavailable.
                    #
                    # We read the SAME already-rolled card `confirm_reads` times and
                    # require them to agree on the stat set before trusting it. A
                    # re-read costs no kuva (we are not cycling), so this is a free
                    # correctness guard against flaky/bled OCR. If the reads never
                    # agree, the roll is untrusted and MUST be reverted, never kept.
                    from core.consensus import read_until_consensus

                    _last_frame = {"f": None}

                    # Default-arg binding of the frame holder keeps this closure
                    # free of the loop variable (and is evaluated once per read).
                    def _read_once(_holder=_last_frame):
                        frame = grab_frame(backend="wgc")
                        _holder["f"] = frame
                        return parser.parse(find_riven_stats(frame))

                    consensus = read_until_consensus(
                        _read_once,
                        need=self.confirm_reads,
                        should_stop=sf.is_set,
                    )
                    if sf.is_set(): break
                    parsed = consensus.parsed
                    frame  = _last_frame["f"]
                    consensus_ok = consensus.agreed

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

                    # ── 4b. Name-decode override ─────────────────────────────
                    # The riven's NAME deterministically encodes its POSITIVE stats
                    # and OCRs far more reliably than the small stat rows, so we take
                    # the name's positives as authoritative and trust the stat-line
                    # OCR only for the negative (+ values). Falls back to raw OCR if
                    # the name can't be decoded.
                    riven_name = ""
                    name_decode_note = ""
                    try:
                        from core import vision as _vision
                        from core.riven_names import reconcile_parsed_with_name
                        riven_name = _vision.last_riven_name()
                        if riven_name:
                            melee = self.weapon_type in ("melee", "stat sticks")
                            parsed, decoded = reconcile_parsed_with_name(
                                parsed, riven_name, self.weapon, melee=melee
                            )
                            if decoded:
                                name_decode_note = f"name-decode {riven_name!r} -> {sorted(decoded)}"
                            else:
                                name_decode_note = f"name-decode FAILED {riven_name!r} (raw OCR used)"
                        else:
                            name_decode_note = "name-decode SKIPPED (no name OCR'd; raw OCR used)"
                    except Exception as _e:
                        name_decode_note = f"name-decode ERROR: {_e}"

                    # ── 5. Evaluate ───────────────────────────────────────────
                    rule_result = rules.evaluate(parsed, self.profiles)

                    rag_result = {"score": 0.0, "notes": [], "weapon_data": None}
                    if parsed["positives"]:   # only query RAG if we got stats
                        rag_result = rag_mod.score(parsed, self.weapon, self.weapon_type)

                    rag_score = rag_result.get("score", 0.0)

                    # If OCR got nothing at all — treat as bad roll, always revert.
                    ocr_failed = not parsed["positives"] and not parsed["negatives"]

                    # Full accept: a consensus-confirmed profile match. RAG is an
                    # ADVISORY score for ranking near-ties — it must never veto a
                    # roll the user's own rules accepted. In roll-until-match mode a
                    # match is the explicit goal, so we stop on it regardless of RAG;
                    # in ratchet mode we still let a low RAG hold out for something
                    # better, but only when a better roll is actually achievable.
                    full_accept = (
                        consensus_ok
                        and not ocr_failed
                        and rule_result["accept"]
                        and (
                            self.roll_until_match
                            or self.rag_threshold == 0.0
                            or rag_score >= self.rag_threshold
                        )
                    )

                    # Score for "is this roll better than what we have?"
                    # score_roll() returns -9999 for unreadable rolls, so they
                    # can never beat best_score (which starts at -9999 and only
                    # rises when we keep a readable roll). ocr_failed is still
                    # kept as an extra guard for full_accept gating.
                    melee_bonus = rag_result.get("melee_bonus", 0.0)
                    new_score   = rules.score_roll(parsed, self.profiles,
                                                   rag_score, melee_bonus,
                                                   stat_priority=self.stat_priority,
                                                   neg_priority=self.neg_priority)
                    # Safety: market/RAG score may rank acceptable rolls, but it
                    # must never cause us to keep a roll that failed user rules.
                    #
                    # roll_until_match mode: never ratchet to a "best-so-far". Only
                    # a full profile match is worth keeping — everything else is
                    # reverted so the riven ends exactly on the roll the user wants.
                    is_better   = (
                        consensus_ok
                        and (not self.roll_until_match)
                        and (not ocr_failed)
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
                    # Card name rides along with every roll event so the desktop
                    # Roll Log and the phone companion keep it for the record.
                    rag_result["riven_name"]  = riven_name
                    # Record the triple-check outcome so diagnostics show whether a
                    # revert was due to an unstable/disagreeing read.
                    rag_result.setdefault("notes", [])
                    if self.confirm_reads > 1:
                        if consensus_ok:
                            rag_result["notes"].append(
                                f"consensus: {self.confirm_reads} reads agreed "
                                f"(attempt {consensus.attempts}, {consensus.reads_taken} reads)"
                            )
                        else:
                            rag_result["notes"].append(
                                f"consensus FAILED: {self.confirm_reads} reads never agreed "
                                f"after {consensus.reads_taken} reads → reverting (untrusted read)"
                            )

                    if self.on_roll:
                        self.on_roll(roll_num, parsed, rule_result, rag_result,
                                     full_accept)

                    # ── Debug file log ────────────────────────────────────────
                    if full_accept and not ocr_failed:
                        _decision_str = "ACCEPTED"
                    elif is_better:
                        _decision_str = "NEW BEST"
                    else:
                        _decision_str = "REVERT"
                    try:
                        from core.vision import _blacklisted_lines, _last_cluster_debug
                        # Surface which OCR column was picked as the new card, so a
                        # diagnostic export shows whether new-vs-equipped separation
                        # worked. (Free, logging-only.)
                        rag_result.setdefault("notes", []).append(f"OCR {_last_cluster_debug}")
                        if name_decode_note:
                            rag_result["notes"].append(name_decode_note)
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
                            riven_name        = riven_name,
                        )
                    except Exception:
                        pass   # never let logging crash the rolling loop

                    # ── 6. Keep or revert ─────────────────────────────────────
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
                        # Worse, equal, or OCR failed — revert. Pass the new roll's
                        # stats so revert_roll can VERIFY it selected the OLD card
                        # (different stats) before confirming, never keeping the new.
                        if automation.revert_roll(sf, new_parsed=parsed): break

                    # Reached the end of a full, clean roll — clear the hiccup
                    # budget so only back-to-back failures ever stop the session.
                    consecutive_hiccups = 0

                except Exception as e:
                    # A transient UI hiccup — recover instead of ending the run.
                    consecutive_hiccups += 1
                    last_hiccup = (str(e).splitlines() or [""])[0] or e.__class__.__name__
                    try:
                        rlog.log_note(
                            f"Recoverable hiccup on roll #{roll_num} "
                            f"({consecutive_hiccups}/{MAX_CONSECUTIVE_HICCUPS}): {last_hiccup}"
                        )
                    except Exception:
                        pass
                    if consecutive_hiccups >= MAX_CONSECUTIVE_HICCUPS:
                        self._finish(
                            f"STOPPED after {consecutive_hiccups} consecutive UI hiccups "
                            f"near roll #{roll_num} (last: {last_hiccup}). Warframe may "
                            f"have left the riven screen, lost focus, or been closed. "
                            f"Best: {best_summary} | Kuva: ~{kuva_spent:,}"
                        )
                        return
                    # Best-effort return to a cycle-ready screen (reverts any
                    # unresolved roll), then let the loop try again.
                    if automation.recover_to_cycle(sf):
                        break   # stop requested during recovery

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
        finally:
            # Bulletproof: whatever path the thread exits by (stop, finish,
            # crash), never leave ALT / a mouse button stuck — that is what
            # wedges the Windows taskbar after a session.
            try:
                from core.automation import release_input_state
                release_input_state()
            except Exception:
                pass

    def _finish(self, reason: str):
        try:
            from core import roll_logger as rlog
            rlog.log_session_end(reason)
        except Exception:
            pass
        try:
            from core.automation import release_input_state
            release_input_state()
        except Exception:
            pass
        if self.on_done:
            self.on_done(reason)
