"""
OCR wrapper using Windows built-in OCR via winocr.

Zero ML dependencies — uses the Windows.Media.Ocr WinRT API that ships
with every copy of Windows 10/11. No torch, no onnxruntime, no DLLs.

Uses winocr.recognize_pil_sync() — no asyncio required.
"""

from PIL import Image

_engine_available: bool | None = None  # checked lazily


def _check_available() -> bool:
    global _engine_available
    if _engine_available is None:
        try:
            import winocr
            _engine_available = True
        except Exception:
            _engine_available = False
    return _engine_available


def read_image(img: Image.Image, confidence_threshold: float = 0.0, **_kwargs) -> list[tuple[str, float]]:
    """
    Run Windows OCR on a PIL Image.

    Returns list of (text, confidence) tuples.
    Windows OCR doesn't expose per-word confidence, so confidence is always 1.0.
    Results are returned in top-to-bottom reading order (WinRT preserves this).
    """
    if not _check_available():
        raise RuntimeError("winocr not available — run: pip install winocr")

    import winocr

    result = winocr.recognize_pil_sync(img, "en")

    lines_out = []
    for line in result.get("lines", []):
        text = line.get("text", "").strip()
        if text:
            lines_out.append((text, 1.0))
    return lines_out


def extract_lines(img: Image.Image, **_kwargs) -> list[str]:
    """Convenience: return just the text lines."""
    return [text for text, _ in read_image(img)]
