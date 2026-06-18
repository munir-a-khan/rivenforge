"""
Typed core domain objects for riven parsing and rule evaluation.

These classes are intentionally GUI- and OCR-free. They are safe to use from
tests, CLI tooling, fixture replay, and future GUI screens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

Decision = Literal["KEEP", "ROLL", "REVIEW"]


class ParseStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    EMPTY = "empty"


@dataclass(frozen=True)
class StatRef:
    """Normalized stat identity."""

    id: str
    name: str


@dataclass(frozen=True)
class RivenStat:
    stat_id: str
    name: str
    value: float
    polarity: Literal["positive", "negative"]
    raw_line: str

    def to_legacy(self) -> dict[str, Any]:
        return {"stat": self.name, "value": self.value}


@dataclass(frozen=True)
class ParserIssue:
    code: str
    message: str
    raw_line: str | None = None


@dataclass(frozen=True)
class ParseResult:
    positives: tuple[RivenStat, ...] = ()
    negatives: tuple[RivenStat, ...] = ()
    raw_lines: tuple[str, ...] = ()
    issues: tuple[ParserIssue, ...] = ()
    confidence: float = 1.0
    status: ParseStatus = ParseStatus.EMPTY

    @property
    def stats(self) -> tuple[RivenStat, ...]:
        return self.positives + self.negatives

    @property
    def is_complete_enough(self) -> bool:
        return self.status == ParseStatus.OK

    def to_legacy(self) -> dict[str, Any]:
        dropped_sanity = [
            issue.raw_line or issue.message
            for issue in self.issues
            if issue.code == "impossible_value"
        ]
        dropped_dupes = [
            issue.raw_line or issue.message
            for issue in self.issues
            if issue.code == "duplicate_stat"
        ]
        return {
            "positives": [s.to_legacy() for s in self.positives],
            "negatives": [s.to_legacy() for s in self.negatives],
            "raw_lines": list(self.raw_lines),
            "dropped_sanity": dropped_sanity,
            "dropped_dupes": dropped_dupes,
            "confidence": self.confidence,
            "status": self.status.value,
            "issues": [
                {"code": i.code, "message": i.message, "raw_line": i.raw_line}
                for i in self.issues
            ],
        }


@dataclass(frozen=True)
class StatSlot:
    """A profile slot. Empty accepted_stat_ids means any positive stat."""

    accepted_stat_ids: tuple[str, ...] = ()
    label: str = "Any"

    @property
    def is_any(self) -> bool:
        return not self.accepted_stat_ids


@dataclass(frozen=True)
class OrGroup:
    slots: tuple[StatSlot, ...]
    min_required: int
    label: str = "required positives"


@dataclass(frozen=True)
class RollProfile:
    name: str
    positive_groups: tuple[OrGroup, ...]
    safe_negative_ids: tuple[str, ...] = ()
    rejected_negative_ids: tuple[str, ...] = ()
    required_negative_ids: tuple[str, ...] = ()
    min_negatives_required: int = 0
    schema_version: int = 1


@dataclass(frozen=True)
class RuleTrace:
    code: str
    message: str
    matched: bool


@dataclass(frozen=True)
class RuleDecision:
    decision: Decision
    accept: bool
    profile_matched: str | None = None
    details: str = ""
    traces: tuple[RuleTrace, ...] = field(default_factory=tuple)

    def to_legacy(self) -> dict[str, Any]:
        return {
            "accept": self.accept,
            "profile_matched": self.profile_matched,
            "details": self.details,
            "decision": self.decision,
            "traces": [
                {"code": t.code, "message": t.message, "matched": t.matched}
                for t in self.traces
            ],
        }
