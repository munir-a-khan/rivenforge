from PIL import Image

from core.analysis import analyze_pipeline_result
from core.models import OrGroup, RollProfile, StatSlot
from core.ocr_pipeline import ScreenshotSource, StaticTextOcrEngine, run_ocr_pipeline


def _image(path):
    Image.new("RGB", (800, 600), color=(0, 0, 0)).save(path)


def test_pipeline_replays_screenshot_with_static_ocr(tmp_path):
    path = tmp_path / "roll.png"
    _image(path)

    result = run_ocr_pipeline(
        ScreenshotSource(path),
        crop_mode="full",
        ocr_engine=StaticTextOcrEngine((
            "+100% Critical Chance",
            "+80% Critical Damage",
            "-30% Impact",
        )),
        preprocess=False,
    )

    assert result.safe_for_rule_decision
    assert result.parse.status.value == "ok"
    assert result.parse.positives[0].stat_id == "critical_chance"


def test_pipeline_low_confidence_requires_review(tmp_path):
    path = tmp_path / "roll.png"
    _image(path)

    result = run_ocr_pipeline(
        ScreenshotSource(path),
        crop_mode="full",
        ocr_engine=StaticTextOcrEngine((
            "+100% Critical Chance",
            "+80% Critical Damage",
        ), confidence=0.4),
        preprocess=False,
        min_confidence=0.75,
    )

    assert not result.safe_for_rule_decision
    assert "confidence" in result.review_reasons[0].lower()


def test_analysis_returns_review_for_partial_ocr(tmp_path):
    path = tmp_path / "roll.png"
    _image(path)
    pipeline = run_ocr_pipeline(
        ScreenshotSource(path),
        crop_mode="full",
        ocr_engine=StaticTextOcrEngine(("+100% Critical Chance",)),
        preprocess=False,
    )
    profile = RollProfile(
        name="Critical",
        positive_groups=(OrGroup((StatSlot(("critical_chance",), "Critical Chance"),), 1),),
    )

    analysis = analyze_pipeline_result(pipeline, [profile])

    assert analysis.decision.decision == "REVIEW"
    assert analysis.decision.accept is False


def test_pipeline_writes_debug_artifacts(tmp_path):
    path = tmp_path / "roll.png"
    debug_dir = tmp_path / "debug"
    _image(path)

    result = run_ocr_pipeline(
        ScreenshotSource(path),
        crop_mode="full",
        ocr_engine=StaticTextOcrEngine((
            "+100% Critical Chance",
            "+80% Critical Damage",
        )),
        preprocess=False,
        debug_dir=debug_dir,
    )

    assert result.debug_dir == str(debug_dir)
    assert (debug_dir / "raw.png").exists()
    assert (debug_dir / "ocr.txt").read_text(encoding="utf-8").startswith("+100%")
