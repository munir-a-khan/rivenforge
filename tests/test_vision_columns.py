"""
Centre-card read tests for core.vision.find_riven_stats.

The NEW (just-rolled) riven is always the SELECTED card, which Warframe
promotes to the centre of the screen and brightens; the old/equipped riven
sits dimmed to the left. find_riven_stats crops tightly to that centre card
so the old card physically cannot bleed into the OCR (the failure mode that
poisoned reads when we OCR'd the full width: winocr merged text from both
cards into single lines, and consensus re-reads happily agreed on the stable
contamination).

These tests monkeypatch _ocr_screen; it receives the CROPPED image, which
lets us assert the crop geometry as well as the line filtering.
"""

from PIL import Image

from core import vision


def _mock_items(lines):
    """OCR items for the centre-card crop, already top-to-bottom."""
    return [
        {"cx": 150, "cy": 20 + 30 * i, "text": t, "x": 100, "y": 20 + 30 * i, "w": 100, "h": 20}
        for i, t in enumerate(lines)
    ]


def test_crop_is_centre_card_only(monkeypatch):
    """The OCR must see ONLY the centre-card region, not the full frame."""
    seen = {}

    def fake_ocr(img):
        seen["size"] = img.size
        return []

    monkeypatch.setattr(vision, "_ocr_screen", fake_ocr)
    vision.find_riven_stats(Image.new("RGB", (1920, 1080)))
    w, h = seen["size"]
    # Crop is 43–60% of width (~326px): narrow enough that the old card at
    # ~36% x (text ending ~42%) is out of frame and can't contaminate the read,
    # but wide enough for the widest stat line. Vertically it's generous
    # (48–83%) so a wrapped stat name or wrapped card title can't push a stat
    # out of frame. It must never be a near-full-width read.
    assert w < 1920 * 0.22, f"crop too wide (old card could bleed): {w}px"
    assert h < 1080 * 0.40, f"crop unexpectedly short: {h}px"


def test_reads_selected_card_stats(monkeypatch):
    lines = [
        "Quatz Sati-lexitox",       # card name — no digits, filtered
        "+2.9 Punch Through",
        "+134.3% Multishot",
        "+94.7% *Toxin",
        "+80.7% Weapon Recoil",
        "MR 13",                     # UI text — skip phrase
        "695",                       # reroll count — no % / sign+name
    ]
    monkeypatch.setattr(vision, "_ocr_screen", lambda img: _mock_items(lines))
    out = vision.find_riven_stats(Image.new("RGB", (1920, 1080)))
    assert out == [
        "+2.9 Punch Through",
        "+134.3% Multishot",
        "+94.7% *Toxin",
        "+80.7% Weapon Recoil",
    ]


def test_hard_caps_at_four_stat_lines(monkeypatch):
    lines = [f"+{10 + i}% Damage" for i in range(6)]
    monkeypatch.setattr(vision, "_ocr_screen", lambda img: _mock_items(lines))
    out = vision.find_riven_stats(Image.new("RGB", (1920, 1080)))
    assert len(out) == 4


def test_wrapped_stat_name_is_merged(monkeypatch):
    # The UI wraps long names onto a second row inside the card.
    lines = [
        "+139.8% Status",
        "Chance",
        "-26.9% Magazine",
        "Capacity",
    ]
    monkeypatch.setattr(vision, "_ocr_screen", lambda img: _mock_items(lines))
    out = vision.find_riven_stats(Image.new("RGB", (1920, 1080)))
    assert out == ["+139.8% Status Chance", "-26.9% Magazine Capacity"]


def test_empty_ocr_returns_empty(monkeypatch):
    monkeypatch.setattr(vision, "_ocr_screen", lambda img: [])
    assert vision.find_riven_stats(Image.new("RGB", (1920, 1080))) == []
