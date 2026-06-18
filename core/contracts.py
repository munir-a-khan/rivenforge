"""
TypedDict contracts for every legacy dict shape that crosses the
GUI ↔ core/rag boundary.

These types do two jobs:

1. **They serve as the source of truth for the FastAPI/React migration.**
   When the React frontend codegens TypeScript types from the FastAPI
   OpenAPI schema, every shape here becomes a TS type. Drift can't sneak
   in because mypy/pydantic will reject it server-side.
2. **They document the surface today** so a new dev can read one file and
   know exactly what every cross-boundary call expects and returns.

The legacy functions (`parser.parse`, `rules.evaluate`, `rag.rag.score`,
etc.) continue to return plain `dict` at runtime — these types just
describe the shape. The typed/dataclass versions (`ParseResult`,
`RuleDecision`, `RivenAnalysis`) remain the preferred internal path; the
dict mirrors exist for the GUI surface and the future JSON API.

Nothing here changes runtime behavior. This is a documentation +
type-checking pass only.
"""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

# ── 1. Parser output ─────────────────────────────────────────────────────

ParseStatusStr = Literal["ok", "partial", "empty"]


class RivenStatDict(TypedDict):
    """One parsed stat line. Returned by `parser.parse`."""
    stat: str
    value: float


class ParserIssueDict(TypedDict):
    """A line the parser couldn't use. From `ParseResult.to_legacy`."""
    code: str
    message: str
    raw_line: str | None


class ParsedRollDict(TypedDict):
    """Legacy dict shape from `core.parser.parse(...)`."""
    positives: list[RivenStatDict]
    negatives: list[RivenStatDict]
    raw_lines: list[str]
    dropped_sanity: list[str]
    dropped_dupes: list[str]
    confidence: float
    status: ParseStatusStr
    issues: list[ParserIssueDict]


# ── 2. Rule evaluation output ────────────────────────────────────────────

DecisionStr = Literal["KEEP", "ROLL", "REVIEW"]


class RuleTraceDict(TypedDict):
    """A single check the rule engine ran."""
    code: str
    message: str
    matched: bool


class RuleEvaluationDict(TypedDict):
    """Legacy dict shape from `core.rules.evaluate(...)`."""
    accept: bool
    profile_matched: str | None
    details: str
    decision: DecisionStr
    traces: list[RuleTraceDict]


# ── 3. Roll profile (legacy dict) ────────────────────────────────────────

class RollProfileDict(TypedDict):
    """The dict shape stored in user_config.json `profiles` array.

    The typed `RollProfile` dataclass (`core.models.RollProfile`) is the
    preferred internal type. This dict mirror is what the GUI and the
    JSON config file use.
    """
    name: str
    desired_positives: list[str]
    min_positives_required: int
    acceptable_negatives: list[str]
    rejected_negatives: NotRequired[list[str]]
    required_negatives: NotRequired[list[str]]
    min_negatives_required: NotRequired[int]
    schema_version: NotRequired[int]


# ── 4. Weapon entries (riven_index.json + tier list) ─────────────────────

WeaponTypeStr = Literal[
    "primary", "secondary", "melee", "archgun", "robotic", "stat sticks"
]


class WeaponEntryDict(TypedDict):
    """One row from the tier list. Returned by `rag.ingest.all_weapons`,
    `rag.ingest.weapon_lookup`, and used by `rules.default_profiles_from_weapon_data`."""
    weapon: str
    weapon_type: WeaponTypeStr
    positives: list[str]
    negatives: list[str]
    notes: NotRequired[str]
    text_chunk: NotRequired[str]


# ── 5. RAG / WFM scoring output ──────────────────────────────────────────

WfmSourceStr = Literal["wfm", "none"]


class RagScoreDict(TypedDict, total=False):
    """Returned by `rag.rag.score(...)`.

    `total=False` because some keys are added later by the roller
    (`kuva_cost`, `kuva_total`, `new_score`, `best_score`, `is_better`),
    not by `score()` itself."""
    score: float
    notes: list[str]
    weapon_data: WeaponEntryDict | None
    plat_low: int | None
    plat_median: int | None
    plat_score: float
    melee_bonus: float
    wfm_source: WfmSourceStr
    # Added by roller before passing to on_roll callback:
    kuva_cost: int
    kuva_total: int
    new_score: float
    best_score: float
    is_better: bool


# ── 6. Vision / button detection ─────────────────────────────────────────

ButtonName = Literal[
    "cycle_button", "cycle_yes", "cycle_no",
    "confirm_button", "keep_yes", "keep_no",
]


class ButtonPositionsDict(TypedDict, total=False):
    """Returned by `core.vision.find_all_buttons`.

    Each value is `(cx, cy)` in window-local pixel coords, or `None` if
    the button text wasn't found in the frame. `_all_text` is a debug
    bag of every OCR hit (text, cx, cy) for diagnostic display."""
    cycle_button: tuple[int, int] | None
    cycle_yes: tuple[int, int] | None
    cycle_no: tuple[int, int] | None
    confirm_button: tuple[int, int] | None
    keep_yes: tuple[int, int] | None
    keep_no: tuple[int, int] | None
    _all_text: list[tuple[str, int, int]]


# ── 7. Capture metadata (carried on PIL Image.info) ──────────────────────

CapturePathStr = Literal["mss", "dxgi", "mss(dark)"]


class CaptureInfoDict(TypedDict):
    """Metadata attached to `grab_frame()`'s returned `PIL.Image.info`."""
    brightness: int
    black_frame: bool
    capture_path: CapturePathStr


# ── 8. Button coordinate config ──────────────────────────────────────────

class ButtonCoordsDict(TypedDict):
    """The `button_coords` block in user_config.json. Each value is a
    `[x, y]` pixel pair in screen-relative coords."""
    cycle_button: list[int]
    cycle_yes: list[int]
    confirm_button: list[int]
    keep_yes: list[int]
    keep_no: list[int]


# ── 9. User config (data_util.load_config / save_config) ─────────────────

class UserConfigDict(TypedDict):
    """The full shape of `config/user_config.json`. Source of truth."""
    weapon: str
    weapon_type: WeaponTypeStr
    profiles: list[RollProfileDict]
    roll_limit: int
    rag_threshold: float
    animation_wait: float
    button_coords: ButtonCoordsDict


# ── 10. Roller event payloads (RollerThread → GUI callbacks) ─────────────

class RollerOnRollPayload(TypedDict):
    """Args passed to `RollerThread.on_roll(roll_num, parsed, rule_result, rag_result, accepted)`.

    Not actually used as a dict at runtime — it's destructured into
    positional args — but defined here so the future WebSocket event
    shape lines up with the in-process callback shape."""
    roll_num: int
    parsed: ParsedRollDict
    rule_result: RuleEvaluationDict
    rag_result: RagScoreDict
    accepted: bool


# ── 11. Roll-log persisted event (one entry per roll in roll_debug.log) ──

DecisionLabel = Literal["ACCEPTED", "NEW BEST", "REVERT"]


class RollLogEntry(TypedDict):
    """The structured shape we want each per-roll log line to take when
    the file logger is replaced by JSONL events streamed over WS."""
    timestamp: str         # ISO-8601
    roll_num: int
    kuva_cost: int
    kuva_total: int
    parsed: ParsedRollDict
    rule_result: RuleEvaluationDict
    rag_result: RagScoreDict
    new_score: float
    best_score: float
    decision: DecisionLabel
    capture_path: CapturePathStr
    brightness: int
    ocr_confidence: float
    blacklisted_lines: NotRequired[list[str]]


__all__ = [
    # Parser
    "ParseStatusStr", "RivenStatDict", "ParserIssueDict", "ParsedRollDict",
    # Rules
    "DecisionStr", "RuleTraceDict", "RuleEvaluationDict",
    # Profiles
    "RollProfileDict",
    # Weapon data
    "WeaponTypeStr", "WeaponEntryDict",
    # RAG
    "WfmSourceStr", "RagScoreDict",
    # Vision
    "ButtonName", "ButtonPositionsDict",
    # Capture
    "CapturePathStr", "CaptureInfoDict",
    # Config
    "ButtonCoordsDict", "UserConfigDict",
    # Roller events
    "RollerOnRollPayload", "DecisionLabel", "RollLogEntry",
]
