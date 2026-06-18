from core.models import OrGroup, RollProfile, StatSlot
from core.parser import parse_result
from core.rules import evaluate, evaluate_result


def _profile_2_pos_1_neg() -> RollProfile:
    return RollProfile(
        name="Two plus safe neg",
        positive_groups=(
            OrGroup(
                slots=(
                    StatSlot(("critical_chance",), "Critical Chance"),
                    StatSlot(("critical_damage",), "Critical Damage"),
                    StatSlot(("damage",), "Damage"),
                ),
                min_required=2,
            ),
        ),
        safe_negative_ids=("impact",),
    )


def test_two_positive_plus_one_safe_negative_matches():
    parsed = parse_result([
        "+100% Critical Chance",
        "+80% Critical Damage",
        "-30% Impact",
    ])

    decision = evaluate_result(parsed, [_profile_2_pos_1_neg()])

    assert decision.decision == "KEEP"
    assert decision.accept
    assert decision.profile_matched == "Two plus safe neg"


def test_three_positive_plus_one_negative_matches():
    parsed = parse_result([
        "+100% Critical Chance",
        "+80% Critical Damage",
        "+120% Damage",
        "-30% Impact",
    ])
    profile = RollProfile(
        name="Three plus safe neg",
        positive_groups=(
            OrGroup(
                slots=(
                    StatSlot(("critical_chance",), "Critical Chance"),
                    StatSlot(("critical_damage",), "Critical Damage"),
                    StatSlot(("damage",), "Damage"),
                ),
                min_required=3,
            ),
        ),
        safe_negative_ids=("impact",),
    )

    decision = evaluate_result(parsed, [profile])

    assert decision.decision == "KEEP"
    assert decision.accept


def test_or_group_slot_matches_either_stat():
    parsed = parse_result([
        "+100% Critical Chance",
        "+80% Electricity",
    ])
    profile = RollProfile(
        name="OR group",
        positive_groups=(
            OrGroup(
                slots=(
                    StatSlot(("critical_damage", "electricity"), "CD or Electricity"),
                    StatSlot(("critical_chance",), "Critical Chance"),
                ),
                min_required=2,
            ),
        ),
    )

    decision = evaluate_result(parsed, [profile])

    assert decision.decision == "KEEP"


def test_any_slot_matches_any_positive_stat():
    parsed = parse_result([
        "+100% Status Chance",
        "+80% Cold",
    ])
    profile = RollProfile(
        name="Any slot",
        positive_groups=(
            OrGroup(
                slots=(
                    StatSlot(("status_chance",), "Status Chance"),
                    StatSlot((), "Any"),
                ),
                min_required=2,
            ),
        ),
    )

    decision = evaluate_result(parsed, [profile])

    assert decision.decision == "KEEP"


def test_any_slot_does_not_double_count_the_same_stat():
    parsed = parse_result([
        "+100% Status Chance",
        "-30% Impact",
    ])
    profile = RollProfile(
        name="Any needs second stat",
        positive_groups=(
            OrGroup(
                slots=(
                    StatSlot(("status_chance",), "Status Chance"),
                    StatSlot((), "Any"),
                ),
                min_required=2,
            ),
        ),
        safe_negative_ids=("impact",),
    )

    decision = evaluate_result(parsed, [profile])

    assert decision.decision == "ROLL"
    assert "missing required" in decision.details.lower()


def test_two_positive_plus_required_negative_matches():
    parsed = parse_result([
        "+100% Critical Chance",
        "+80% Critical Damage",
        "-30% Impact",
    ])
    profile = RollProfile(
        name="2p1n",
        positive_groups=(
            OrGroup(
                slots=(
                    StatSlot(("critical_chance",), "Critical Chance"),
                    StatSlot(("critical_damage",), "Critical Damage"),
                ),
                min_required=2,
            ),
        ),
        safe_negative_ids=("impact",),
        required_negative_ids=("impact",),
        min_negatives_required=1,
    )

    decision = evaluate_result(parsed, [profile])

    assert decision.decision == "KEEP"


def test_required_negative_missing_fails():
    parsed = parse_result([
        "+100% Critical Chance",
        "+80% Critical Damage",
    ])
    profile = RollProfile(
        name="Needs negative",
        positive_groups=(
            OrGroup(
                slots=(
                    StatSlot(("critical_chance",), "Critical Chance"),
                    StatSlot(("critical_damage",), "Critical Damage"),
                ),
                min_required=2,
            ),
        ),
        safe_negative_ids=("impact",),
        required_negative_ids=("impact",),
        min_negatives_required=1,
    )

    decision = evaluate_result(parsed, [profile])

    assert decision.decision == "ROLL"
    assert "missing required negative" in decision.details.lower()


def test_rejected_negative_fails_with_explanation():
    parsed = parse_result([
        "+100% Critical Chance",
        "+80% Critical Damage",
        "-30% Impact",
    ])
    profile = RollProfile(
        name="No impact",
        positive_groups=(
            OrGroup(
                slots=(
                    StatSlot(("critical_chance",), "Critical Chance"),
                    StatSlot(("critical_damage",), "Critical Damage"),
                ),
                min_required=2,
            ),
        ),
        safe_negative_ids=("impact",),
        rejected_negative_ids=("impact",),
    )

    decision = evaluate_result(parsed, [profile])

    assert decision.decision == "ROLL"
    assert "rejected negative" in decision.details.lower()


def test_partial_ocr_returns_review():
    parsed = parse_result(["+100% Critical Chance"])

    decision = evaluate_result(parsed, [_profile_2_pos_1_neg()])

    assert decision.decision == "REVIEW"
    assert not decision.accept


def test_failed_roll_explains_missing_required_stat():
    parsed = parse_result([
        "+100% Critical Chance",
        "+80% Status Chance",
    ])

    decision = evaluate_result(parsed, [_profile_2_pos_1_neg()])

    assert decision.decision == "ROLL"
    assert "missing required" in decision.details.lower()


def test_legacy_evaluate_returns_trace_and_decision():
    parsed = {
        "positives": [{"stat": "Critical Chance", "value": 100.0}],
        "negatives": [],
        "status": "partial",
    }
    profiles = [{"name": "Legacy", "desired_positives": ["Critical Chance"], "min_positives_required": 1}]

    result = evaluate(parsed, profiles)

    assert result["decision"] == "REVIEW"
    assert result["accept"] is False
    assert result["traces"][0]["code"] == "parse_status"
