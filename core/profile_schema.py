"""
Versioned roll profile schema helpers.

This is deliberately small for Milestone 1: it validates and normalizes the
current dict profile format into typed RollProfile objects. Later migrations can
be added here without touching GUI code or the rule engine.
"""

from __future__ import annotations

from typing import Any

from core.models import OrGroup, RollProfile, StatSlot
from core.stat_registry import display_name, normalize_many

CURRENT_PROFILE_SCHEMA_VERSION = 1


class ProfileSchemaError(ValueError):
    pass


def load_profile(data: dict[str, Any]) -> RollProfile:
    version = int(data.get("schema_version", CURRENT_PROFILE_SCHEMA_VERSION))
    if version != CURRENT_PROFILE_SCHEMA_VERSION:
        raise ProfileSchemaError(f"Unsupported profile schema_version: {version}")

    name = str(data.get("name") or "Unnamed")

    if "positive_groups" in data:
        groups: list[OrGroup] = []
        for raw_group in data["positive_groups"]:
            min_required = int(raw_group.get("min_required", 1))
            group_slots: list[StatSlot] = []
            for raw_slot in raw_group.get("slots", []):
                ids = normalize_many(tuple(raw_slot.get("accepted_stats", [])))
                label = str(raw_slot.get("label") or ("Any" if not ids else " / ".join(display_name(i) for i in ids)))
                group_slots.append(StatSlot(ids, label))
            if not group_slots:
                raise ProfileSchemaError(f"Profile '{name}' has an empty positive group")
            groups.append(OrGroup(tuple(group_slots), min_required, str(raw_group.get("label") or "required positives")))
    else:
        desired = normalize_many(tuple(data.get("desired_positives", [])))
        min_required = int(data.get("min_positives_required", 2))
        legacy_slots = tuple(StatSlot((stat_id,), display_name(stat_id)) for stat_id in desired)
        if not legacy_slots:
            raise ProfileSchemaError(f"Profile '{name}' must include desired positives or positive groups")
        groups = [OrGroup(legacy_slots, min_required, "required positives")]

    return RollProfile(
        name=name,
        positive_groups=tuple(groups),
        safe_negative_ids=normalize_many(tuple(data.get("acceptable_negatives", data.get("safe_negatives", [])))),
        rejected_negative_ids=normalize_many(tuple(data.get("rejected_negatives", []))),
        required_negative_ids=normalize_many(tuple(data.get("required_negatives", []))),
        min_negatives_required=int(data.get("min_negatives_required", 0)),
        schema_version=version,
    )


def dump_profile(profile: RollProfile) -> dict[str, Any]:
    return {
        "schema_version": profile.schema_version,
        "name": profile.name,
        "positive_groups": [
            {
                "label": group.label,
                "min_required": group.min_required,
                "slots": [
                    {
                        "label": slot.label,
                        "accepted_stats": [display_name(stat_id) for stat_id in slot.accepted_stat_ids],
                    }
                    for slot in group.slots
                ],
            }
            for group in profile.positive_groups
        ],
        "safe_negatives": [display_name(stat_id) for stat_id in profile.safe_negative_ids],
        "rejected_negatives": [display_name(stat_id) for stat_id in profile.rejected_negative_ids],
        "required_negatives": [display_name(stat_id) for stat_id in profile.required_negative_ids],
        "min_negatives_required": profile.min_negatives_required,
    }
