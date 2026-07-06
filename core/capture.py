"""
Screen capture and riven card region detection.

Two capture paths:

  1. **mss** (GDI / BitBlt) — fast, works for Windowed and Borderless
     Windowed. Returns a black frame when Warframe is in Fullscreen
     Exclusive because GDI can't reach the DX framebuffer.
  2. **dxcam** (DXGI Desktop Duplication) — reads the actual display
     output at the hardware level, works in all three display modes
     including Fullscreen Exclusive. Slower to initialize so we cache
     the camera per output index.

Strategy: try mss first, check average brightness, fall back to dxcam if
the frame is black. The Warframe window's monitor is detected via
``MonitorFromWindow`` so multi-monitor users with Warframe on a secondary
display capture the right output.
"""

import threading
import time
from typing import Any

import numpy as np
from PIL import Image

try:
    import mss
    HAS_MSS = True
except Exception:  # pragma: no cover - headless/container import guard
    mss = None  # type: ignore[assignment]
    HAS_MSS = False

try:
    import win32api
    import win32con
    import win32gui
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

try:
    import dxcam
    HAS_DXCAM = True
except ImportError:
    dxcam = None  # type: ignore[assignment]
    HAS_DXCAM = False

from core import capture_wgc


def _warframe_window_rect():
    """Return (left, top, right, bottom) of the Warframe window, or None."""
    if not HAS_WIN32:
        return None
    hwnd = win32gui.FindWindow(None, "Warframe")
    if not hwnd:
        return None
    rect = win32gui.GetWindowRect(hwnd)
    return rect  # (left, top, right, bottom)


def warframe_window_status() -> dict[str, Any]:
    """Return non-invasive Warframe window/capture status for diagnostics."""
    status: dict[str, Any] = {
        "available": HAS_WIN32,
        "found": False,
        "visible": False,
        "minimized": False,
        "foreground": False,
        "rect": None,
        "capture_backends": {
            "mss": HAS_MSS,
            "dxcam": HAS_DXCAM,
            "windows_graphics_capture": capture_wgc.is_available(),
        },
        "notes": [],
    }
    if not HAS_WIN32:
        status["notes"].append("pywin32 is not available on this platform.")
        return status

    hwnd = win32gui.FindWindow(None, "Warframe")
    if not hwnd:
        status["notes"].append("Warframe window was not found.")
        return status

    rect = tuple(int(value) for value in win32gui.GetWindowRect(hwnd))
    status.update({
        "found": True,
        "visible": bool(win32gui.IsWindowVisible(hwnd)),
        "minimized": bool(win32gui.IsIconic(hwnd)),
        "foreground": win32gui.GetForegroundWindow() == hwnd,
        "rect": rect,
    })

    status["hwnd"] = int(hwnd)

    if status["minimized"]:
        if capture_wgc.is_available():
            status["notes"].append(
                "Warframe is minimized; a minimized window has no surface to "
                "capture, so the WGC path will briefly restore it WITHOUT taking "
                "focus (it may appear behind your current window) so it can be read."
            )
        else:
            status["notes"].append(
                "Warframe is minimized; no backend can read a minimized window and "
                "WGC (which can restore-without-focus) is not installed."
            )
    elif not status["foreground"]:
        if capture_wgc.is_available():
            status["notes"].append(
                "Warframe is unfocused; the WGC backend can capture it even if it is "
                "covered by another window. mss/DXGI only work if it is uncovered."
            )
        else:
            status["notes"].append(
                "Warframe is unfocused; OCR works if the window stays uncovered. "
                "Install windows-capture for covered-window (WGC) capture."
            )
    if not HAS_DXCAM:
        status["notes"].append("dxcam is not installed; fullscreen/DXGI fallback is unavailable.")
    if not capture_wgc.is_available():
        status["notes"].append("windows-capture is not installed; covered-window (WGC) capture is unavailable.")
    return status


_BLACK_FRAME_BRIGHTNESS = 12  # average luminance below this may be black
_BLACK_FRAME_P95 = 28         # bright-pixel percentile below this confirms black


def _avg_brightness(img: Image.Image) -> int:
    """
    Quick average luminance over a downsampled grayscale view.
    A normal riven card frame averages 30–80; a Fullscreen-Exclusive
    capture that GDI couldn't reach averages near 0.
    """
    small = img.convert("L").resize((64, 64), Image.NEAREST)
    return int(np.array(small, dtype=np.uint16).mean())


def _brightness_stats(img: Image.Image) -> tuple[int, int]:
    """
    Return (average, p95) luminance over a downsampled image.

    Warframe's riven screen can have a low average brightness while still
    containing bright readable UI. A true black capture has both low average
    and low high-percentile brightness.
    """
    small = img.convert("L").resize((96, 54), Image.NEAREST)
    arr = np.array(small, dtype=np.uint16)
    return int(arr.mean()), int(np.percentile(arr, 95))


def _is_black_frame(img: Image.Image) -> bool:
    avg, p95 = _brightness_stats(img)
    return avg < _BLACK_FRAME_BRIGHTNESS and p95 < _BLACK_FRAME_P95


# ── DXGI fallback (Fullscreen Exclusive) ────────────────────────────────────
#
# dxcam cameras are heavy GPU resources: ~1 s to create, but subsequent
# .grab() calls are sub-millisecond. We cache one per output_idx and serialize
# access with a lock — dxcam isn't documented thread-safe and the GUI test
# panel can race the roll thread otherwise.

_dxcam_lock     = threading.Lock()
_dxcam_cameras: dict[int, "dxcam.DXCamera"] = {}
_dxcam_failed   = False   # latched after first failed import or .create()


def _warframe_monitor_info() -> tuple[int, tuple[int, int, int, int]] | None:
    """
    Return ``(output_idx, monitor_rect_in_virtual_coords)`` for the display
    containing the Warframe window. The output index corresponds to dxcam's
    enumeration of physical outputs.
    """
    if not HAS_WIN32:
        return None
    hwnd = win32gui.FindWindow(None, "Warframe")
    if not hwnd:
        return None
    try:
        hmon = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)
        monitors = win32api.EnumDisplayMonitors()
        for idx, (mon_handle, _hdc, _rect) in enumerate(monitors):
            if int(mon_handle) == int(hmon):
                info = win32api.GetMonitorInfo(hmon)
                # 'Monitor' = (left, top, right, bottom) in virtual desktop coords
                return idx, tuple(info["Monitor"])  # type: ignore[return-value]
    except Exception:
        return None
    return None


def _get_dxcam_camera(output_idx: int):
    """Get-or-create a dxcam camera for the given output. ``None`` on failure."""
    global _dxcam_failed
    if not HAS_DXCAM or _dxcam_failed:
        return None
    cam = _dxcam_cameras.get(output_idx)
    if cam is not None:
        return cam
    try:
        cam = dxcam.create(output_idx=output_idx, output_color="RGB")
    except Exception:
        _dxcam_failed = True
        return None
    if cam is None:
        _dxcam_failed = True
        return None
    _dxcam_cameras[output_idx] = cam
    return cam


def _capture_via_dxgi(virtual_rect: tuple[int, int, int, int] | None) -> Image.Image | None:
    """
    Capture using DXGI Desktop Duplication. ``virtual_rect`` is the Warframe
    window rect in virtual desktop coords; it's translated to monitor-local
    coords for dxcam.
    """
    if not HAS_DXCAM:
        return None

    with _dxcam_lock:
        mon = _warframe_monitor_info()
        if mon is None:
            # Warframe window not found — try primary output, full screen.
            output_idx = 0
            region = None
        else:
            output_idx, mon_rect = mon
            if virtual_rect is None:
                region = None
            else:
                ml, mt, _mr, _mb = mon_rect
                vl, vt, vr, vb = virtual_rect
                # Clamp to monitor bounds; dxcam refuses regions outside output.
                region = (
                    max(0, vl - ml),
                    max(0, vt - mt),
                    max(1, vr - ml),
                    max(1, vb - mt),
                )

        cam = _get_dxcam_camera(output_idx)
        if cam is None:
            return None

        # grab() returns None when no frame is available since the last call
        # (DXGI is event-driven). Retry briefly.
        arr = None
        for _ in range(8):
            try:
                arr = cam.grab(region=region) if region else cam.grab()
            except Exception:
                return None
            if arr is not None:
                break
            time.sleep(0.04)
        if arr is None:
            return None
    return Image.fromarray(arr)


# ShowWindow flag: restore a minimized window to its previous size WITHOUT
# activating it (so we don't steal keyboard focus from whatever app the user
# is actually using). SW_SHOWNOACTIVATE == 4.
_SW_SHOWNOACTIVATE = 4


def _restore_without_focus(hwnd: int) -> bool:
    """
    Un-minimize a window without activating it. Returns True if the window is
    (now) not minimized.

    A minimized DirectX window has no composed surface, so NO capture backend
    can read it — this is an OS constraint, not a rivenforge limit. Rather than
    fail, we restore the window with SW_SHOWNOACTIVATE, which brings its surface
    back while leaving keyboard focus on the user's foreground app. The window
    becomes visible (it may sit behind other windows), which is the price of
    reading a "minimized" game non-invasively.
    """
    if not HAS_WIN32:
        return False
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, _SW_SHOWNOACTIVATE)
            time.sleep(0.12)  # let DWM recompose the surface
        return not win32gui.IsIconic(hwnd)
    except Exception:
        return False


def _capture_via_wgc(restore_if_minimized: bool = True) -> Image.Image | None:
    """Capture the Warframe window via WGC, or None if unavailable/failed."""
    if not (HAS_WIN32 and capture_wgc.is_available()):
        return None
    hwnd = win32gui.FindWindow(None, "Warframe")
    if not hwnd:
        return None
    if win32gui.IsIconic(hwnd):
        # Minimized: restore without focus so WGC has a surface to read.
        if not restore_if_minimized or not _restore_without_focus(hwnd):
            return None
    return capture_wgc.capture_window(hwnd)


def grab_frame(monitor_index: int = 0, backend: str = "auto") -> Image.Image:
    """
    Capture the screen (or the Warframe window).

    ``backend``:
      - ``"auto"`` (default): mss first (fast, Windowed / Borderless
        Windowed), fall back to dxcam / DXGI Desktop Duplication if the
        frame is black (Fullscreen Exclusive). Best for foreground /
        visible-and-uncovered Warframe.
      - ``"wgc"``: capture the Warframe *window* via Windows.Graphics.
        Capture. Works even when the window is covered by another app,
        unfocused, or on a second monitor — the background scenario. Falls
        back to the ``"auto"`` ladder if WGC is unavailable or fails.

    The returned image carries:
      - ``info["brightness"]``    average luminance 0–255
      - ``info["black_frame"]``   True if brightness is below threshold
      - ``info["capture_path"]``  "mss" | "dxgi" | "mss(dark)" | "wgc"
    """
    if backend == "wgc":
        wgc_img = _capture_via_wgc()
        if wgc_img is not None:
            brightness, p95 = _brightness_stats(wgc_img)
            wgc_img.info["brightness"] = brightness
            wgc_img.info["brightness_p95"] = p95
            wgc_img.info["black_frame"] = _is_black_frame(wgc_img)
            wgc_img.info["capture_path"] = "wgc"
            return wgc_img
        # WGC unavailable/failed — fall through to the auto ladder below.

    if not HAS_MSS:
        raise RuntimeError(
            "Screen capture is unavailable: the 'mss' backend is not installed. "
            "Live/desktop capture requires a Windows host with a display."
        )

    rect = _warframe_window_rect()
    with mss.mss() as sct:
        if rect:
            left, top, right, bottom = rect
            region = {"left": left, "top": top, "width": right - left, "height": bottom - top}
        else:
            monitors = sct.monitors  # index 0 = all, 1 = primary, etc.
            idx = min(monitor_index + 1, len(monitors) - 1)
            region = sct.monitors[idx]

        shot = sct.grab(region)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

    brightness, p95 = _brightness_stats(img)
    capture_path = "mss"

    if _is_black_frame(img):
        dxgi_img = _capture_via_dxgi(rect)
        if dxgi_img is not None:
            dxgi_brightness, dxgi_p95 = _brightness_stats(dxgi_img)
            if dxgi_brightness > brightness:
                img          = dxgi_img
                brightness   = dxgi_brightness
                p95          = dxgi_p95
                capture_path = "dxgi"
        if capture_path == "mss" and _is_black_frame(img):
            capture_path = "mss(dark)"

    img.info["brightness"]   = brightness
    img.info["brightness_p95"] = p95
    img.info["black_frame"]  = _is_black_frame(img)
    img.info["capture_path"] = capture_path
    return img


def preprocess_for_ocr(img: Image.Image) -> Image.Image:
    """
    Enhance the riven card image for the Windows WinRT OCR engine.

    Two steps, in this order:

      1. **Grayscale.** Colored element glyphs (❄ Cold, 🔥 Heat, ☠ Toxin,
         ⚡ Electricity) are treated as graphics by WinRT OCR and the whole
         line gets dropped. Converting to grayscale flattens those glyphs
         into neutral shapes and the text on either side reads fine.
      2. **Linear contrast stretch** ``[20, 235] → [0, 255]`` to push the
         white card text toward pure white and the violet background toward
         pure black.

    Two things we DO NOT do, on purpose:

      * **No upscaling.** Lanczos resampling of crisply-rendered UI text
         introduces ringing around digit strokes — exactly the artifact
         that turns ``+128.4%`` into ``+1284%`` or ``+178.4%``. FrameForge
         landed on the same conclusion; we follow their lead.
      * **No CLAHE / adaptive contrast.** Adaptive equalization is great
         for natural images but amplifies local noise around UI text. A
         flat linear stretch is more predictable.
    """
    # Use int32 so the (value-20) * 255 multiplication can't overflow.
    arr = np.array(img.convert("L"), dtype=np.int32)
    arr = ((arr - 20) * 255 // 215).clip(0, 255).astype(np.uint8)
    return Image.fromarray(arr).convert("RGB")


def crop_riven_card_region(img: Image.Image) -> Image.Image:
    """
    Crop the single-card view (pre-roll screen).
    Center 40% width × 35–85% height.
    """
    w, h = img.size
    left   = int(w * 0.30)
    right  = int(w * 0.70)
    top    = int(h * 0.35)
    bottom = int(h * 0.85)
    return img.crop((left, top, right, bottom))


def crop_new_card_region(img: Image.Image) -> Image.Image:
    """
    Crop the NEW (right-side) card from the side-by-side comparison view.

    After clicking CYCLE → YES → animation, Warframe shows:
      [OLD card]  [NEW card]  CONFIRM button
    The new card is on the RIGHT half of screen, roughly:
      X: 50–75% of width, Y: 25–80% of height

    From the 1920x1080 screenshots:
      New card roughly occupies x=480–840 (of 1456-wide view) → ~33–58%
      Scaled to 1920: x=960–1440 → 50–75%
    """
    w, h = img.size
    left   = int(w * 0.42)
    right  = int(w * 0.59)
    top    = int(h * 0.42)
    bottom = int(h * 0.76)
    return img.crop((left, top, right, bottom))
