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

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from core.contracts import ParsedRollDict
from core.stat_registry import normalize_stat

# How many matching reads a stat set needs before we trust it, and the ceiling
# on total reads before we give up. A read is FREE (no kuva), so we can afford
# to keep reading until a stable set emerges.
DEFAULT_CONFIRM_READS = 3
DEFAULT_MAX_READS = 15

# Physical limits of a real Warframe riven. A read outside these is a bled /
# garbage frame and must never count toward consensus.
MAX_POSITIVES = 3
MAX_NEGATIVES = 1


def _is_physically_possible(parsed: ParsedRollDict | dict) -> bool:
    npos = len(parsed.get("positives", []))
    nneg = len(parsed.get("negatives", []))
    return 0 < npos <= MAX_POSITIVES and nneg <= MAX_NEGATIVES


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
    max_reads: int = DEFAULT_MAX_READS,
    should_stop: Callable[[], bool] | None = None,
) -> ConsensusResult:
    """
    Read the current card repeatedly and return the FIRST stat set that is
    confirmed by ``need`` reads.

    Tolerant by design: reads are tallied by signature across ALL attempts, so
    a couple of noisy or bled frames in between don't reset progress — as soon
    as any one plausible stat set has been seen ``need`` times AND holds a
    strict majority of the plausible reads so far, it's accepted. Empty reads
    (mid-animation) and physically-impossible reads (>3 positives / >1 negative
    — i.e. adjacent-card bleed) are ignored entirely so they can neither win
    nor block consensus.

    Returns ``agreed=False`` with the best (modal) read if no set reaches
    ``need`` within ``max_reads`` — the caller must then NOT keep the roll.
    Honours ``should_stop`` so a stop request breaks out promptly.
    """
    if need < 1:
        need = 1
    max_reads = max(max_reads, need)

    counts: Counter[frozenset[tuple[str, str]]] = Counter()
    by_sig: dict[frozenset[tuple[str, str]], ParsedRollDict | dict] = {}
    last: ParsedRollDict | dict = {"positives": [], "negatives": []}
    reads_taken = 0

    while reads_taken < max_reads:
        if should_stop is not None and should_stop():
            break
        last = read_fn()
        reads_taken += 1

        if not _is_physically_possible(last):
            continue  # empty / bled frame — ignore, don't let it win or block
        sig = parsed_signature(last)
        if not sig:
            continue
        counts[sig] += 1
        by_sig[sig] = last

        top_sig, top_n = counts.most_common(1)[0]
        plausible_reads = sum(counts.values())
        # Confirmed: seen `need` times AND a strict majority of plausible reads,
        # so one recurring bled variant can't sneak past a real set.
        if top_n >= need and top_n * 2 > plausible_reads:
            return ConsensusResult(by_sig[top_sig], True, reads_taken, reads_taken, top_sig)

    if counts:
        top_sig, top_n = counts.most_common(1)[0]
        return ConsensusResult(by_sig[top_sig], False, reads_taken, reads_taken, top_sig)
    return ConsensusResult(last, False, reads_taken, reads_taken, frozenset())
