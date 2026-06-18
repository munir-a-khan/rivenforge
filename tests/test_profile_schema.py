import pytest

from core.profile_schema import ProfileSchemaError, dump_profile, load_profile


def test_load_legacy_profile_schema_v1():
    profile = load_profile({
        "schema_version": 1,
        "name": "Melee",
        "desired_positives": ["Critical Chance", "Critical Damage", "Damage"],
        "min_positives_required": 2,
        "acceptable_negatives": ["Impact"],
    })

    assert profile.name == "Melee"
    assert profile.positive_groups[0].min_required == 2
    assert profile.safe_negative_ids == ("impact",)


def test_load_group_profile_with_any_slot():
    profile = load_profile({
        "schema_version": 1,
        "name": "Grouped",
        "positive_groups": [
            {
                "label": "main",
                "min_required": 2,
                "slots": [
                    {"label": "CD or Damage", "accepted_stats": ["Critical Damage", "Damage"]},
                    {"label": "Any", "accepted_stats": []},
                ],
            }
        ],
        "safe_negatives": ["Impact"],
        "required_negatives": ["Impact"],
        "min_negatives_required": 1,
        "rejected_negatives": ["Zoom"],
    })

    assert profile.positive_groups[0].slots[0].accepted_stat_ids == ("critical_damage", "damage")
    assert profile.positive_groups[0].slots[1].is_any
    assert profile.required_negative_ids == ("impact",)
    assert profile.min_negatives_required == 1
    assert profile.rejected_negative_ids == ("zoom",)


def test_dump_profile_uses_display_names():
    profile = load_profile({
        "name": "Exportable",
        "desired_positives": ["CC", "CD"],
        "min_positives_required": 2,
    })

    dumped = dump_profile(profile)

    assert dumped["schema_version"] == 1
    assert dumped["positive_groups"][0]["slots"][0]["accepted_stats"] == ["Critical Chance"]


def test_empty_profile_is_invalid():
    with pytest.raises(ProfileSchemaError):
        load_profile({"name": "Empty", "desired_positives": []})
