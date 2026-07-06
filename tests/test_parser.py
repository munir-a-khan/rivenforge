from core.models import ParseStatus
from core.parser import parse, parse_result


def test_over_count_read_is_invalid_never_keepable():
    # The exact Quatz Critapha mis-keep from the diagnostics: the real riven
    # was only Heat + Critical Chance, but OCR bled the left (equipped) card's
    # Fire Rate + Critical Damage in, producing FOUR positives. A riven can
    # never have 4 positives, so this must be INVALID (-> REVIEW/REVERT),
    # never eligible for KEEP.
    result = parse_result([
        "+87.8% Fire Rate",
        "+1 16.7% Critical Damage Quatz Critapha",
        "+110.4% *Heat",
        "+187.7% Critical Chance",
    ])
    assert result.status == ParseStatus.INVALID
    assert not result.is_complete_enough
    assert any(i.code == "impossible_stat_count" for i in result.issues)


def test_two_negatives_is_invalid():
    # A riven has at most one negative; two genuine negatives means bleed.
    # (Recoil is NOT used here: -recoil inverts to a positive.)
    result = parse_result([
        "+120% Critical Chance",
        "-30% Fire Rate",
        "-45% Damage",
    ])
    assert result.status == ParseStatus.INVALID


def test_normal_three_positive_one_negative_still_ok():
    # The cap must NOT reject a legitimate max-stat riven (3 pos + 1 neg).
    result = parse_result([
        "+120% Critical Chance",
        "+90% Critical Damage",
        "+80% Multishot",
        "-30% Fire Rate",
    ])
    assert result.status == ParseStatus.OK


def test_parse_recovers_negative_buried_in_ocr_bleed():
    # Real failure from roll_debug.log: this nukor roll was wrongly ACCEPTED
    # as a clean 2-positive because the "-35% Status Duration" negative was
    # dropped — OCR read "-35a%" and the weapon name "Nukor Acriata" bled onto
    # the line, diluting the whole-string fuzzy match below threshold.
    result = parse_result([
        "+387% Ammo Maximum x1 .22 Damage to Infested Fire Rate",
        "-35a% status Duration Nukor Acriata",
        "+57.8% Critical Damage",
        "+126.5% Damage",
    ])

    pos_ids = [s.stat_id for s in result.positives]
    neg = {s.stat_id: s.value for s in result.negatives}
    # The negative must be recovered — this is what stops the bot keeping a bad roll.
    assert neg.get("status_duration") == -35.0
    # And the clean positives still parse; no phantom from the "x1 .22" garbage.
    assert "critical_damage" in pos_ids
    assert "damage" in pos_ids
    assert "ammo_maximum" in pos_ids
    assert "damage_to_infested" not in pos_ids  # orphan-decimal phantom is suppressed


def test_parse_extracts_multiple_stats_from_one_merged_line():
    # OCR sometimes merges two stats onto one line. Both must be recovered.
    result = parse_result([
        "+120% Critical Chance +80% Critical Damage",
        "-30% Reload Speed",
    ])
    assert [s.stat_id for s in result.positives] == ["critical_chance", "critical_damage"]
    assert [s.stat_id for s in result.negatives] == ["reload_speed"]


def test_parse_result_normalizes_positive_and_negative_stats():
    result = parse_result([
        "+102.6% Status Chance",
        "+63.3% Attack Speed",
        "-7.3s Combo Duration",
    ])

    assert result.status == ParseStatus.OK
    assert [stat.stat_id for stat in result.positives] == ["status_chance", "attack_speed"]
    assert result.negatives[0].stat_id == "combo_duration"
    assert result.negatives[0].value == -7.3


def test_parse_result_marks_single_stat_as_partial():
    result = parse_result(["+153.6% Impact"])

    assert result.status == ParseStatus.PARTIAL
    assert not result.is_complete_enough


def test_parse_result_drops_impossible_values_and_duplicates():
    result = parse_result([
        "+2226% Critical Chance",
        "+80% Critical Chance",
        "+81% CC",
    ])

    assert result.status == ParseStatus.PARTIAL
    assert [stat.stat_id for stat in result.positives] == ["critical_chance"]
    assert {issue.code for issue in result.issues} == {"impossible_value", "duplicate_stat"}


def test_parse_result_inverts_recoil_polarity_so_plus_is_negative():
    # In Warframe, +Recoil makes the gun harder to control (BAD) while
    # -Recoil makes it easier (GOOD). The card prints the raw delta but
    # the rule engine + scoring need the inverted view so all positives
    # and negatives compare apples to apples across stat lines.
    result = parse_result([
        "+182.5% Damage",
        "+108.9% Heat",
        "+73.1% Weapon Recoil",   # alias for Recoil
    ])

    assert result.status == ParseStatus.OK
    assert [s.stat_id for s in result.positives] == ["damage", "heat"]
    # The Weapon Recoil alias resolved to recoil AND the polarity flipped:
    assert [s.stat_id for s in result.negatives] == ["recoil"]
    assert result.negatives[0].value == -73.1   # sign flipped to negative
    assert result.negatives[0].polarity == "negative"


def test_parse_result_inverts_recoil_polarity_so_minus_is_positive():
    # The reverse case: a riven that REDUCES recoil is good for the player.
    # -30% Recoil should appear as a positive with magnitude 30.
    result = parse_result([
        "+120% Critical Damage",
        "-30% Recoil",
    ])

    assert result.status == ParseStatus.OK
    pos_ids = [s.stat_id for s in result.positives]
    assert "recoil" in pos_ids
    recoil = next(s for s in result.positives if s.stat_id == "recoil")
    assert recoil.value == 30.0
    assert recoil.polarity == "positive"
    assert result.negatives == ()


def test_parse_result_strips_heavy_attack_decorator_for_any_stat():
    # The "(x2 for Heavy Attacks)" suffix is a display annotation, not a
    # stat-identifying token. Any rolled stat that supports heavy attacks
    # can show it, so we strip it at normalization time instead of keeping
    # a per-stat alias.
    result = parse_result([
        "+128.4% Critical Chance for Slide Attack",
        "+115.5% Critical Damage (x2 for Heavy Attacks)",
        "-66% Damage (x2 for Heavy Attacks)",
    ])

    assert result.status == ParseStatus.OK
    assert [stat.stat_id for stat in result.positives] == [
        "slide_critical_chance",
        "critical_damage",
    ]
    assert [stat.stat_id for stat in result.negatives] == ["damage"]


def test_parse_result_strips_bow_and_other_weapon_class_decorators():
    # Boltor (and other bow-line weapons) print "(x2 for Bows)" next to the
    # Fire Rate on a riven. Before this regression was caught, the parser
    # silently dropped the entire stat line — log lines like
    #   '+86.4% Fire Rate (x2 for Bows)'
    #   '-57% Fire Rate (x2 for Bows)'
    # produced 0 positives / 0 negatives for the Fire Rate line.
    result = parse_result([
        "+110.8% Multishot",
        "+194.5% Damage",
        "+99.3% Status Chance",
        "-57% Fire Rate (x2 for Bows)",
    ])

    assert result.status == ParseStatus.OK
    assert [s.stat_id for s in result.positives] == [
        "multishot", "damage", "status_chance",
    ]
    assert [s.stat_id for s in result.negatives] == ["fire_rate"]
    assert result.negatives[0].value == -57.0


def test_parse_result_resolves_initial_combo_variants():
    # Warframe displays Initial Combo under several different names
    # depending on weapon class. They all map to the same rolled stat.
    for ui_text in (
        "+66% Additional Combo Count Chance",
        "+66% Chance to Gain Combo Count",
        "+66% Chance to Gain Extra Combo Count",
        "+66% Combo Count Chance",
    ):
        result = parse_result([ui_text])
        assert result.positives, f"failed to detect: {ui_text!r}"
        assert result.positives[0].stat_id == "initial_combo", (
            f"{ui_text!r} -> {result.positives[0].stat_id!r}"
        )


def test_parse_result_merges_wrapped_ui_stat_names():
    # The Warframe riven UI wraps long stat names onto a second visual line,
    # which OCR returns as a separate item. Without merging, the slide
    # variant collapses to plain "Critical Chance" and collides with the
    # heavy-attack line below it.
    result = parse_result([
        "+128.4% Critical Chance",
        "for Slide Attack",
        "+204.8% Melee Damage",
        "+229.1% Critical Chance",
        "(x2 for Heavy Attacks)",
        "-93.7% Chance to Gain",
        "Combo Count",
    ])

    assert result.status == ParseStatus.OK
    assert [stat.stat_id for stat in result.positives] == [
        "slide_critical_chance",
        "melee_damage",
        "critical_chance",
    ]
    assert [stat.stat_id for stat in result.negatives] == ["initial_combo"]
    assert result.negatives[0].value == -93.7


def test_legacy_parse_shape_is_preserved():
    parsed = parse(["+88.1% Cold", "+118.3% Finisher Damage"])

    assert parsed["status"] == "ok"
    assert parsed["positives"] == [
        {"stat": "Cold", "value": 88.1},
        {"stat": "Finisher Damage", "value": 118.3},
    ]
    assert parsed["negatives"] == []
