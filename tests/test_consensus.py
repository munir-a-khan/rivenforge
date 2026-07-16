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
    assert result.reads_taken == 3


def test_disagreeing_reads_never_reach_consensus():
    # Every call returns a different stat set (bleed that shifts frame to
    # frame); no set is ever seen `need` times. Consensus must fail -> revert.
    seq = iter([
        _roll([("Heat", 110), ("Critical Chance", 187)]),
        _roll([("Toxin", 90), ("Multishot", 100)]),
        _roll([("Damage", 200), ("Range", 50)]),
    ] * 10)
    result = read_until_consensus(lambda: next(seq), need=3, max_reads=6)
    assert result.agreed is False


def test_empty_reads_never_count_as_consensus():
    result = read_until_consensus(lambda: _roll([]), need=3, max_reads=6)
    assert result.agreed is False


def test_over_count_reads_are_ignored_and_do_not_block():
    # THE FIELD BUG: the good roll (3 stats) kept getting a bled 4-positive
    # frame mixed in. The bled reads are physically impossible (>3 positives)
    # and must be ignored so the real 3-stat set still reaches consensus.
    good = _roll([("Fire Rate", 69.8), ("Damage", 179.3), ("Status Chance", 86.8)])
    bled = _roll([
        ("Fire Rate", 69.8), ("Damage", 179.3),
        ("Status Chance", 86.8), ("Critical Chance", 187.7), ("Heat", 110.4),
    ])  # 5 positives — adjacent-card bleed
    seq = iter([good, bled, good, bled, good] * 4)
    result = read_until_consensus(lambda: next(seq), need=3, max_reads=15)
    assert result.agreed is True
    assert parsed_signature(result.parsed) == parsed_signature(good)


def test_majority_reaches_consensus_despite_noise():
    # 2 good reads + 1 different, repeating. The good set holds a majority and
    # reaches `need`, so it's confirmed rather than reverted forever.
    good = _roll([("Toxin", 90), ("Multishot", 100)])
    noise = _roll([("Cold", 120)])
    seq = iter([good, noise, good, good, noise, good] * 4)
    result = read_until_consensus(lambda: next(seq), need=3, max_reads=15)
    assert result.agreed is True
    assert parsed_signature(result.parsed) == parsed_signature(good)
