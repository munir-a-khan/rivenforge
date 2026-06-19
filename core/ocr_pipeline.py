"""
OCR pipeline services.

The pipeline deliberately stops at structured parse output and validation. It
does not decide KEEP/ROLL; rule evaluation receives only structured riven data.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from PIL import Image

from core.capture import crop_new_card_region, crop_riven_card_region, grab_frame, preprocess_for_ocr
from core.models import ParseResult
from core.parser import parse_result

CropMode = Literal["full", "single_card", "new_card"]
OcrEngine = Callable[[Image.Image], list[tuple[str, float]]]


class ImageSource(Protocol):
    def capture(self) -> Image.Image:
        ...


@dataclass(frozen=True)
class ScreenCaptureSource:
    monitor_index: int = 0

    def capture(self) -> Image.Image:
        return grab_frame(self.monitor_index)


@dataclass(frozen=True)
class ScreenshotSource:
    path: str | Path

    def capture(self) -> Image.Image:
        return Image.open(self.path).convert("RGB")


@dataclass(frozen=True)
class StaticTextOcrEngine:
    """Test/replay helper for known OCR text fixtures."""

    lines: tuple[str, ...]
    confidence: float = 1.0

    def __call__(self, _img: Image.Image) -> list[tuple[str, float]]:
        return [(line, self.confidence) for line in self.lines]


@dataclass(frozen=True)
class OcrPipelineResult:
    raw_image_size: tuple[int, int]
    crop_image_size: tuple[int, int]
    raw_ocr_lines: tuple[str, ...]
    cleaned_lines: tuple[str, ...]
    line_confidences: tuple[float, ...]
    average_confidence: float
    parse: ParseResult
    review_reasons: tuple[str, ...]
    capture_info: dict[str, Any]
    debug_dir: str | None = None

    @property
    def safe_for_rule_decision(self) -> bool:
        return not self.review_reasons


def cleanup_ocr_text(text: str) -> str:
    return (
        text.strip()
        .replace("\u2212", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\uff0b", "+")
        .replace("\uff0d", "-")
        .replace("  ", " ")
    )


def _default_ocr_engine(img: Image.Image) -> list[tuple[str, float]]:
    from core.ocr import read_image

    return read_image(img)


def _crop(img: Image.Image, crop_mode: CropMode) -> Image.Image:
    if crop_mode == "single_card":
        return crop_riven_card_region(img)
    if crop_mode == "new_card":
        return crop_new_card_region(img)
    return img


def _save_debug(
    debug_dir: str | Path,
    raw: Image.Image,
    cropped: Image.Image,
    preprocessed: Image.Image,
    cleaned_lines: tuple[str, ...],
    result: ParseResult,
) -> str:
    target = Path(debug_dir)
    target.mkdir(parents=True, exist_ok=True)
    raw.save(target / "raw.png")
    cropped.save(target / "cropped.png")
    preprocessed.save(target / "preprocessed.png")
    (target / "ocr.txt").write_text("\n".join(cleaned_lines), encoding="utf-8")
    (target / "parser.txt").write_text(str(result.to_legacy()), encoding="utf-8")
    return str(target)


def run_ocr_pipeline(
    source: ImageSource,
    *,
    crop_mode: CropMode = "new_card",
    ocr_engine: OcrEngine | None = None,
    min_confidence: float = 0.75,
    debug_dir: str | Path | None = None,
    preprocess: bool = True,
) -> OcrPipelineResult:
    raw = source.capture()
    cropped = _crop(raw, crop_mode)
    prepared = preprocess_for_ocr(cropped) if preprocess else cropped

    engine = ocr_engine or _default_ocr_engine
    ocr_output = engine(prepared)
    raw_lines = tuple(line for line, _confidence in ocr_output)
    cleaned_lines = tuple(cleanup_ocr_text(line) for line in raw_lines if cleanup_ocr_text(line))
    confidences = tuple(float(confidence) for _line, confidence in ocr_output)
    average_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    parsed = parse_result(list(cleaned_lines), confidence=average_confidence)

    review_reasons: list[str] = []
    # A black frame almost always means Warframe is in Fullscreen Exclusive
    # mode — GDI/BitBlt returns black because it can't reach the DX
    # framebuffer. Flag it loudly so the user doesn't think the bot
    # silently missed a god roll.
    if raw.info.get("black_frame"):
        brightness = raw.info.get("brightness", 0)
        review_reasons.append(
            f"Black frame (avg brightness {brightness}): "
            "Warframe is likely in Fullscreen Exclusive — switch to "
            "Borderless Windowed in Display settings so capture works."
        )
    if average_confidence < min_confidence:
        review_reasons.append(f"OCR confidence {average_confidence:.2f} below threshold {min_confidence:.2f}")
    if not parsed.is_complete_enough:
        review_reasons.append(f"Parse status is {parsed.status.value}")

    saved_debug_dir = None
    if debug_dir:
        saved_debug_dir = _save_debug(debug_dir, raw, cropped, prepared, cleaned_lines, parsed)

    return OcrPipelineResult(
        raw_image_size=raw.size,
        crop_image_size=cropped.size,
        raw_ocr_lines=raw_lines,
        cleaned_lines=cleaned_lines,
        line_confidences=confidences,
        average_confidence=average_confidence,
        parse=parsed,
        review_reasons=tuple(review_reasons),
        capture_info=dict(raw.info or {}),
        debug_dir=saved_debug_dir,
    )


def analyze_screenshot(
    path: str | Path,
    *,
    crop_mode: CropMode = "new_card",
    ocr_engine: OcrEngine | None = None,
    min_confidence: float = 0.75,
    debug_dir: str | Path | None = None,
) -> OcrPipelineResult:
    return run_ocr_pipeline(
        ScreenshotSource(path),
        crop_mode=crop_mode,
        ocr_engine=ocr_engine,
        min_confidence=min_confidence,
        debug_dir=debug_dir,
    )
