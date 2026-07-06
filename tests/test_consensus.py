from core.consensus import parsed_signature, read_until_consensus


def _roll(pos, neg=None):
    return {
        "positives": [{"stat": s, "value": v} for s, v in pos],
        "negatives": [{"stat": s, "value": v} for s, v in (neg or [])],
    }


def test_signature_ignores_value_jitter_but_keeps_identity():
    a = _roll([("Critical Chance", 116.7)], [("Fire Rate", -30)])
    b = _roll([("Critical Chance", 16.7)], [("Fire Rate", -31)])  # value misread
    assert parsed_signature(a) == parsed_signature(b)


def test_signature_differs_when_stat_set_differs():
    a = _roll([("Critical Chance", 180)])
    b = _roll([("Critical Chance", 180), ("Fire Rate", 90)])  # bled-in extra stat
    assert parsed_signature(a) != parsed_signature(b)


def test_three_agreeing_reads_reach_consensus():
    stable = _roll([("Heat", 110.4), ("Critical Chance", 187.7)])
    result = read_until_consensus(lambda: stable, need=3)
    assert result.agreed is True
    assert result.attempts == 1
    assert result.reads_taken == 3


def test_disagreeing_reads_never_reach_consensus():
    # Simulate a flaky read: every call returns a different stat set (bleed
    # that shifts frame to frame). Consensus must fail -> caller reverts.
    seq = iter([
        _roll([("Heat", 110), ("Critical Chance", 187)]),
        _roll([("Fire Rate", 88), ("Critical Damage", 116), ("Heat", 110), ("Critical Chance", 187)]),
        _roll([("Heat", 110), ("Critical Chance", 187)]),
    ] * 10)
    result = read_until_consensus(lambda: next(seq), need=3, max_attempts=3)
    assert result.agreed is False


def test_empty_reads_never_count_as_consensus():
    # Three identical EMPTY reads must NOT be treated as agreement — an empty
    # card usually means a mid-animation frame.
    result = read_until_consensus(lambda: _roll([]), need=3, max_attempts=2)
    assert result.agreed is False


def test_flaky_then_stable_reaches_consensus_on_retry():
    # First group disagrees, second group is stable -> consensus on attempt 2.
    calls = {"n": 0}
    stable = _roll([("Toxin", 90), ("Multishot", 100)])

    def read():
        calls["n"] += 1
        # Reads 1-3 alternate (disagree); reads 4-6 are all stable.
        if calls["n"] <= 3 and calls["n"] % 2 == 0:
            return _roll([("Toxin", 90)])
        return stable

    result = read_until_consensus(read, need=3, max_attempts=4)
    assert result.agreed is True
    assert result.attempts >= 2
