"""
High-level riven analysis service.

This module is the boundary GUI code should call. It keeps OCR/replay separate
from rule evaluation and guarantees uncertain OCR returns REVIEW.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.models import RollProfile, RuleDecision, RuleTrace
from core.ocr_pipeline import OcrPipelineResult
from core.rules import evaluate_result


@dataclass(frozen=True)
class RivenAnalysis:
    pipeline: OcrPipelineResult
    decision: RuleDecision


def analyze_pipeline_result(
    pipeline_result: OcrPipelineResult,
    profiles: list[RollProfile],
) -> RivenAnalysis:
    if not pipeline_result.safe_for_rule_decision:
        details = "; ".join(pipeline_result.review_reasons) or "OCR result requires review."
        return RivenAnalysis(
            pipeline=pipeline_result,
            decision=RuleDecision(
                decision="REVIEW",
                accept=False,
                details=details,
                traces=tuple(RuleTrace("ocr_validation", reason, False) for reason in pipeline_result.review_reasons),
            ),
        )

    return RivenAnalysis(
        pipeline=pipeline_result,
        decision=evaluate_result(pipeline_result.parse, profiles),
    )
