"""
Multi-profile OR-logic rules engine.

A roll is accepted if ANY of the user's configured profiles matches.
A profile matches when:
  - At least `min_positives_required` of the desired_positives are present
  - Every rolled negative is in the acceptable_negatives whitelist
    (if the roll has no negatives, that's fine)
"""

from rapidfuzz import fuzz

from core.contracts import (
    ParsedRollDict,
    RollProfileDict,
    RuleEvaluationDict,
    WeaponEntryDict,
)
from core.models import (
    OrGroup,
    ParseResult,
    ParseStatus,
    RivenStat,
    RollProfile,
    RuleDecision,
    RuleTrace,
    StatSlot,
)
from core.stat_registry import display_name, normalize_many, normalize_stat


def _stat_in_list(stat_name: str, lst: list[str], threshold: int = 80) -> bool:
    """Return True if stat_name fuzzy-matches any entry in lst."""
    stat_lower = stat_name.lower()
    for item in lst:
        if fuzz.token_sort_ratio(stat_lower, item.lower()) >= threshold:
            return True
    return False


def _stat_from_legacy(entry: dict, polarity: str) -> RivenStat:
    ref = normalize_stat(entry.get("stat", ""))
    name = ref.name if ref else entry.get("stat", "")
    stat_id = ref.id if ref else name.lower().replace(" ", "_")
    return RivenStat(
        stat_id=stat_id,
        name=name,
        value=float(entry.get("value", 0.0)),
        polarity=polarity,  # type: ignore[arg-type]
        raw_line=entry.get("stat", ""),
    )


def parse_result_from_legacy(parsed_stats: dict) -> ParseResult:
    positives = tuple(_stat_from_legacy(s, "positive") for s in parsed_stats.get("positives", []))
    negatives = tuple(_stat_from_legacy(s, "negative") for s in parsed_stats.get("negatives", []))
    status_raw = parsed_stats.get("status")
    if status_raw in {item.value for item in ParseStatus}:
        status = ParseStatus(status_raw)
    else:
        total = len(positives) + len(negatives)
        status = ParseStatus.OK if total >= 2 else ParseStatus.PARTIAL if total == 1 else ParseStatus.EMPTY
    return ParseResult(
        positives=positives,
        negatives=negatives,
        raw_lines=tuple(parsed_stats.get("raw_lines", [])),
        confidence=float(parsed_stats.get("confidence", 1.0)),
        status=status,
    )


def profile_from_legacy(profile: dict) -> RollProfile:
    desired = normalize_many(tuple(profile.get("desired_positives", [])))
    min_required = int(profile.get("min_positives_required", 2))
    slots = tuple(StatSlot((stat_id,), display_name(stat_id)) for stat_id in desired)
    safe_negative_ids = normalize_many(tuple(profile.get("acceptable_negatives", [])))
    return RollProfile(
        name=profile.get("name", "Unnamed"),
        positive_groups=(OrGroup(slots=slots, min_required=min_required),),
        safe_negative_ids=safe_negative_ids,
        rejected_negative_ids=normalize_many(tuple(profile.get("rejected_negatives", []))),
        required_negative_ids=normalize_many(tuple(profile.get("required_negatives", []))),
        min_negatives_required=int(profile.get("min_negatives_required", 0)),
        schema_version=int(profile.get("schema_version", 1)),
    )


def _slot_matches(slot: StatSlot, stat_id: str) -> bool:
    if slot.is_any:
        return True
    return stat_id in slot.accepted_stat_ids


def _match_group(group: OrGroup, rolled_positive_ids: set[str]) -> tuple[bool, int, list[str]]:
    unused = set(rolled_positive_ids)
    matched_count = 0
    missing: list[str] = []

    # Specific slots first, Any slots last, so Any does not consume a stat that
    # a later required specific slot needs.
    slots = sorted(group.slots, key=lambda slot: slot.is_any)
    for slot in slots:
        match = next((stat_id for stat_id in sorted(unused) if _slot_matches(slot, stat_id)), None)
        if match is None:
            missing.append(slot.label)
            continue
        unused.remove(match)
        matched_count += 1

    return matched_count >= group.min_required, matched_count, missing


def _evaluate_profile(parsed: ParseResult, profile: RollProfile) -> RuleDecision:
    traces: list[RuleTrace] = []
    rolled_positive_ids = {stat.stat_id for stat in parsed.positives}
    rolled_negative_ids = {stat.stat_id for stat in parsed.negatives}

    if profile.rejected_negative_ids:
        rejected_hits = sorted(rolled_negative_ids.intersection(profile.rejected_negative_ids))
        if rejected_hits:
            names = ", ".join(display_name(stat_id) for stat_id in rejected_hits)
            traces.append(RuleTrace("rejected_negative", f"Rejected negative present: {names}", False))
            return RuleDecision(
                decision="ROLL",
                accept=False,
                details=f"Profile '{profile.name}' failed: rejected negative present ({names}).",
                traces=tuple(traces),
            )

    if rolled_negative_ids:
        unsafe = sorted(stat_id for stat_id in rolled_negative_ids if stat_id not in profile.safe_negative_ids)
        if unsafe:
            names = ", ".join(display_name(stat_id) for stat_id in unsafe)
            traces.append(RuleTrace("unsafe_negative", f"Unsafe negative present: {names}", False))
            return RuleDecision(
                decision="ROLL",
                accept=False,
                details=f"Profile '{profile.name}' failed: unsafe negative present ({names}).",
                traces=tuple(traces),
            )

    if profile.required_negative_ids:
        required_hits = rolled_negative_ids.intersection(profile.required_negative_ids)
        if len(required_hits) < max(1, profile.min_negatives_required):
            names = ", ".join(display_name(stat_id) for stat_id in profile.required_negative_ids)
            traces.append(RuleTrace("missing_required_negative", f"Missing required negative: {names}", False))
            return RuleDecision(
                decision="ROLL",
                accept=False,
                details=f"Profile '{profile.name}' failed: missing required negative ({names}).",
                traces=tuple(traces),
            )
    elif len(rolled_negative_ids) < profile.min_negatives_required:
        traces.append(
            RuleTrace(
                "missing_required_negative",
                f"Need {profile.min_negatives_required} negative(s), found {len(rolled_negative_ids)}",
                False,
            )
        )
        return RuleDecision(
            decision="ROLL",
            accept=False,
            details=f"Profile '{profile.name}' failed: missing required negative.",
            traces=tuple(traces),
        )

    for group in profile.positive_groups:
        group_ok, matched_count, missing = _match_group(group, rolled_positive_ids)
        traces.append(
            RuleTrace(
                "positive_group",
                f"{group.label}: matched {matched_count}/{group.min_required} required slot(s)",
                group_ok,
            )
        )
        if not group_ok:
            missing_text = ", ".join(missing) if missing else group.label
            return RuleDecision(
                decision="ROLL",
                accept=False,
                details=f"Profile '{profile.name}' failed: missing required positive/group ({missing_text}).",
                traces=tuple(traces),
            )

    traces.append(RuleTrace("profile_match", "All profile requirements matched", True))
    return RuleDecision(
        decision="KEEP",
        accept=True,
        profile_matched=profile.name,
        details=f"Profile '{profile.name}' matched: positives and negatives satisfied.",
        traces=tuple(traces),
    )


def evaluate_result(parsed: ParseResult, profiles: list[RollProfile]) -> RuleDecision:
    """
    Evaluate structured riven data against typed profiles.

    Incomplete parse results always return REVIEW.
    """
    if parsed.status != ParseStatus.OK:
        return RuleDecision(
            decision="REVIEW",
            accept=False,
            details=f"OCR result is {parsed.status.value}; manual review required.",
            traces=(RuleTrace("parse_status", f"Parse status: {parsed.status.value}", False),),
        )

    if not profiles:
        return RuleDecision(
            decision="REVIEW",
            accept=False,
            details="No profiles configured; manual review required.",
            traces=(RuleTrace("no_profiles", "No profiles configured", False),),
        )

    best_failure: RuleDecision | None = None
    best_trace_count = -1
    for profile in profiles:
        result = _evaluate_profile(parsed, profile)
        if result.accept:
            return result
        matched_traces = sum(1 for trace in result.traces if trace.matched)
        if matched_traces > best_trace_count:
            best_failure = result
            best_trace_count = matched_traces

    return best_failure or RuleDecision(decision="ROLL", accept=False, details="No profile matched.")


def _evaluate_legacy_v0(parsed_stats: dict, profiles: list[dict]) -> dict:
    """
    Check parsed_stats against all profiles.

    profiles: list of dicts with keys:
      - name: str
      - desired_positives: list[str]
      - min_positives_required: int (default 2)
      - acceptable_negatives: list[str]

    Returns:
      {
        "accept": bool,
        "profile_matched": str | None,   # name of first matching profile
        "details": str                   # human-readable explanation
      }
    """
    rolled_pos = [s["stat"] for s in parsed_stats.get("positives", [])]
    rolled_neg = [s["stat"] for s in parsed_stats.get("negatives", [])]

    for profile in profiles:
        desired   = profile.get("desired_positives", [])
        min_req   = profile.get("min_positives_required", 2)
        ok_negs   = profile.get("acceptable_negatives", [])

        # Count how many desired stats appear in this roll
        hits = sum(1 for s in rolled_pos if _stat_in_list(s, desired))

        # Check negatives.
        # LOGIC: if ok_negs is non-empty → only those negatives are acceptable.
        #        if ok_negs is empty     → NO negative is acceptable (roll must have no neg).
        # This means leaving acceptable_negatives blank = "I don't want any negatives".
        if ok_negs:
            # Whitelist mode: any neg NOT in ok_negs is bad
            bad_negs = [s for s in rolled_neg if not _stat_in_list(s, ok_negs)]
        else:
            # Strict mode: any negative at all is bad
            bad_negs = list(rolled_neg)

        if hits >= min_req and not bad_negs:
            details = (
                f"Profile '{profile['name']}': "
                f"{hits}/{len(desired)} desired positives matched, "
                f"no bad negatives"
            )
            return {
                "accept": True,
                "profile_matched": profile["name"],
                "details": details,
            }

    # Build rejection summary
    best_hits = 0
    best_name = ""
    for profile in profiles:
        desired = profile.get("desired_positives", [])
        hits = sum(1 for s in rolled_pos if _stat_in_list(s, desired))
        if hits > best_hits:
            best_hits = hits
            best_name = profile["name"]

    details = f"No profile matched. Best: '{best_name}' with {best_hits} hit(s)."
    return {"accept": False, "profile_matched": None, "details": details}


def evaluate(parsed_stats: ParsedRollDict | dict, profiles: list[RollProfileDict | dict]) -> RuleEvaluationDict:
    """Compatibility wrapper around the typed rule engine."""
    parsed = parse_result_from_legacy(parsed_stats)
    typed_profiles = [profile_from_legacy(profile) for profile in profiles]
    return evaluate_result(parsed, typed_profiles).to_legacy()  # type: ignore[return-value]


def score_roll(parsed_stats: ParsedRollDict | dict, profiles: list[RollProfileDict | dict],
               rag_score: float = 0.0,
               melee_bonus: float = 0.0) -> float:
    """
    Return a numeric score for this roll for comparison purposes.
    Higher = better. Used to decide whether to keep a new roll over the current one.

    SCORING DESIGN:
    ─────────────────────────────────────────────────────────────────
    Warframe always gives 2–4 stat lines per roll (usually 3–4 for
    a kuva riven with a negative). If OCR only reads 1 stat we
    almost certainly got a partial read — we must NOT keep a roll
    based on incomplete data.

    Minimum stat threshold
    ──────────────────────
    If total visible stats (pos + neg) < MIN_STATS_TO_TRUST (2),
    the roll is treated as unreadable and scores -9999 so it always
    loses against anything already on the riven (even a previous
    partial read that scored 0).

    Main score formula (when enough stats are visible):
    ────────────────────────────────────────────────────
      profile_score  = hits_count × 200          (absolute hit count, not fraction)
                       + rag_score × 20          (tier-list + WFM price signal, 0–20 pts)
                       + melee_bonus × 80        (melee CD/Range priority, ±0.30 → ±24 pts)
                       – bad_neg_count × 800     (each unacceptable negative)
                       – partial_read_penalty     (if read < expected stats)

    melee_bonus comes from rag/wfm.py and captures:
      +0.15  Critical Damage present (highest melee priority)
      +0.12  Range present
      +0.08  Attack Speed / CC present
      -0.12  IPS or Finisher Damage as a POSITIVE (dead weight on melee)

    Using absolute hit COUNT (not fraction of desired list) means:
      2/3 desired hits scores  400  — better than
      1/3 desired hits scores  200
    regardless of how many stats the profile lists.

    Partial-read penalty:
      If we see fewer than MIN_STATS_TO_TRUST, score = -9999 (handled above).
      If we see only 2 stats total, apply -150 penalty to discourage keeping
      a roll we can't fully verify.

    Result range (typical):
      Perfect read, 3 hits, no bad negs:     ~620
      2 hits, no bad negs:                    ~420
      1 hit, no bad negs:                     ~220
      0 hits, no bad negs:                      ~20 (RAG only)
      Melee: +CD +Range (2 priority hits):   +29 bonus on top
      Bad negative:                           -580 to -380
      Partial read (2 stats):                 -130 to  270
      Unreadable (< 2 stats):               -9999 (always revert)
    ─────────────────────────────────────────────────────────────────
    """
    rolled_pos = [s["stat"] for s in parsed_stats.get("positives", [])]
    rolled_neg = [s["stat"] for s in parsed_stats.get("negatives", [])]
    total_seen = len(rolled_pos) + len(rolled_neg)

    # Hard floor: not enough stats visible — treat as unreadable
    MIN_STATS_TO_TRUST = 2
    if total_seen < MIN_STATS_TO_TRUST:
        return -9999.0

    best_profile_score = -9999.0

    for profile in profiles:
        desired = profile.get("desired_positives", [])
        ok_negs = profile.get("acceptable_negatives", [])
        if not desired:
            continue

        # Absolute number of desired stats hit (NOT a fraction)
        hits = sum(1 for s in rolled_pos if _stat_in_list(s, desired))

        # Bad negative penalty.
        # Same logic as evaluate(): empty ok_negs = NO negatives acceptable.
        if ok_negs:
            bad_negs = [s for s in rolled_neg if not _stat_in_list(s, ok_negs)]
        else:
            bad_negs = list(rolled_neg)   # any negative = bad when whitelist is empty

        # Partial-read penalty: if we see only 2 stats total, dock points
        # since we might be missing a third stat that would change the verdict
        partial_penalty = 150 if total_seen < 3 else 0

        # A roll with ZERO desired hits is worthless regardless of other factors.
        # Force it to a large negative so it never becomes "best so far".
        if hits == 0 and not bad_negs:
            # 0 hits, no bad neg — it's fine but not progress; score near 0
            profile_score = rag_score * 20 + melee_bonus * 80 - partial_penalty - 100
        elif hits == 0:
            # 0 hits AND bad neg — definitely bad
            profile_score = -500.0 - len(bad_negs) * 800
        else:
            profile_score = (
                hits * 200
                + rag_score * 20
                + melee_bonus * 80
                - len(bad_negs) * 800
                - partial_penalty
            )

        if profile_score > best_profile_score:
            best_profile_score = profile_score

    # If no profiles defined, fall back to raw hit count vs any stats
    if best_profile_score == -9999.0:
        best_profile_score = (
            len(rolled_pos) * 50
            + rag_score * 20
            + melee_bonus * 80
        )

    return best_profile_score


def default_profiles_from_weapon_data(weapon_data: WeaponEntryDict | dict) -> list[RollProfileDict]:
    """
    Auto-generate a starter profile from a tier list weapon_data entry.
    Used by the GUI 'Load suggested profiles' button.
    """
    if not weapon_data:
        return []

    pos = weapon_data.get("positives", [])
    neg = weapon_data.get("negatives", [])
    weapon = weapon_data.get("weapon", "Unknown")

    return [{
        "name": f"{weapon} — Tier List Default",
        "desired_positives": pos,
        "min_positives_required": min(2, len(pos)),
        "acceptable_negatives": neg,
    }]
