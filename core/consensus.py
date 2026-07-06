"""
Consensus OCR reading — the "triple-check" before a keep/revert decision.

OCR of the riven card is noisy: the two-card cycle-compare view bleeds the
left (equipped) card in, weapon names mash into stat lines, and digits get
mangled between frames. A single read can therefore be wrong in a way that
survives the physical-limit guard (e.g. a stable-but-bled set).

So before the roller trusts a read enough to KEEP or REVERT on it, we read
the SAME already-rolled card several times and require them to AGREE on the
set of stats. Re-reading the current card costs no kuva (we are not cycling),
so we can retry cheaply until the reads are stable.

This module is deliberately pure and capture-free: it operates on a
``read_fn`` callable that returns a parsed-roll dict, so it is fully testable
without a screen or a game running.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from core.contracts import ParsedRollDict
from core.stat_registry import normalize_stat

# Default number of reads that must agree, and how many times we retry the
# whole group before giving up and treating the read as untrusted.
DEFAULT_CONFIRM_READS = 3
DEFAULT_MAX_ATTEMPTS = 6


def parsed_signature(parsed: ParsedRollDict | dict) -> frozenset[tuple[str, str]]:
    """
    Reduce a parsed roll to its decision-relevant identity: the set of
    ``(polarity, stat_id)`` pairs. Two reads with the same signature describe
    the same roll for keep/revert purposes, even if a value digit jittered.

    Stat names are normalized to canonical IDs so "Critical Chance" and a
    slightly-misread "critical chance" collapse to the same identity.
    """
    sig: set[tuple[str, str]] = set()
    for s in parsed.get("positives", []):
        ref = normalize_stat(str(s.get("stat", "")))
        sig.add(("+", ref.id if ref else str(s.get("stat", "")).lower()))
    for s in parsed.get("negatives", []):
        ref = normalize_stat(str(s.get("stat", "")))
        sig.add(("-", ref.id if ref else str(s.get("stat", "")).lower()))
    return frozenset(sig)


@dataclass(frozen=True)
class ConsensusResult:
    parsed: ParsedRollDict | dict
    agreed: bool
    attempts: int          # how many groups of reads it took
    reads_taken: int       # total individual reads performed
    signature: frozenset[tuple[str, str]]


def read_until_consensus(
    read_fn: Callable[[], ParsedRollDict | dict],
    *,
    need: int = DEFAULT_CONFIRM_READS,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    should_stop: Callable[[], bool] | None = None,
) -> ConsensusResult:
    """
    Call ``read_fn`` in groups of ``need`` reads. If every read in a group
    shares the same (non-empty) signature, return it as agreed. Otherwise
    retry, up to ``max_attempts`` groups.

    Returns the last read with ``agreed=False`` if consensus is never reached
    (the caller should then NOT keep the roll). Honours ``should_stop`` so a
    stop request breaks out promptly.
    """
    if need < 1:
        need = 1
    last: ParsedRollDict | dict = {"positives": [], "negatives": []}
    last_sig: frozenset[tuple[str, str]] = frozenset()
    reads_taken = 0

    for attempt in range(1, max_attempts + 1):
        sigs: list[frozenset[tuple[str, str]]] = []
        for _ in range(need):
            if should_stop is not None and should_stop():
                return ConsensusResult(last, False, attempt, reads_taken, last_sig)
            last = read_fn()
            reads_taken += 1
            last_sig = parsed_signature(last)
            sigs.append(last_sig)

        first = sigs[0]
        # A consensus on an EMPTY read is not trustworthy — an empty card
        # usually means the frame was mid-animation. Require a real stat set.
        if first and all(s == first for s in sigs):
            return ConsensusResult(last, True, attempt, reads_taken, first)

    return ConsensusResult(last, False, max_attempts, reads_taken, last_sig)
