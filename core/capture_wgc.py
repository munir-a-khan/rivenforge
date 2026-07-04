"""
Windows.Graphics.Capture (WGC) backend — per-window capture.

This is the *safe* half of "OBS-style background capture": WGC is a
Microsoft-sanctioned WinRT API (the same one OBS's "Window Capture (WGC)"
source uses). It captures a specific window's composed surface, which is
the one thing mss and DXGI Desktop Duplication cannot do:

  - mss captures a screen *region*  → a window behind another app yields
    the covering app's pixels.
  - DXGI captures the display output → same problem; you get whatever is
    actually on the monitor.
  - WGC captures the *window itself* → works even when the window is
    covered, unfocused, or on a second monitor.

Hard OS limit shared by every backend: a **minimized** window has no
surface to compose, so it cannot be captured. That boundary is documented,
not worked around.

No injection, no hooks, no anti-cheat evasion — this is the documented API
and nothing more. The heavy lifting is done by the `windows-capture`
package (a thin Rust wrapper over WGC); we degrade gracefully to
``is_available() == False`` if it isn't installed.
"""

from __future__ import annotations

import threading
from typing import Any

from PIL import Image

try:
    from windows_capture import WindowsCapture
    HAS_WGC = True
except Exception:  # pragma: no cover - import guard
    WindowsCapture = None
    HAS_WGC = False


def is_available() -> bool:
    """True if the WGC backend can be used on this machine."""
    return HAS_WGC


def capture_window(hwnd: int, timeout: float = 2.0) -> Image.Image | None:
    """
    Grab a single frame of the window identified by ``hwnd`` via WGC.

    Returns a PIL RGB image, or ``None`` if WGC is unavailable, the window
    can't be captured (e.g. minimized), or no frame arrives before
    ``timeout``.

    WGC is a streaming API: we start a free-threaded capture, grab the
    first frame that arrives, immediately stop, and hand the frame back.
    Start-up costs ~100-500ms, which is why this is NOT the default
    ``grab_frame`` path — it's opt-in for the background / covered-window
    scenario.
    """
    if not HAS_WGC or not hwnd:
        return None

    result: dict[str, Any] = {"image": None}
    done = threading.Event()

    try:
        capture = WindowsCapture(
            cursor_capture=False,   # don't composite the mouse cursor into the frame
            draw_border=False,      # no capture-region highlight (newer Win11 only)
            window_hwnd=int(hwnd),
        )
    except Exception:
        return None

    @capture.event
    def on_frame_arrived(frame, capture_control) -> None:
        try:
            bgr = frame.convert_to_bgr()
            buffer = bgr.frame_buffer  # HxWx3 uint8, BGR
            # BGR -> RGB without importing cv2: reverse the last axis.
            rgb = buffer[:, :, ::-1]
            result["image"] = Image.fromarray(rgb, "RGB").copy()
        except Exception:
            result["image"] = None
        finally:
            try:
                capture_control.stop()
            except Exception:
                pass
            done.set()

    @capture.event
    def on_closed() -> None:
        done.set()

    try:
        control = capture.start_free_threaded()
    except Exception:
        return None

    got = done.wait(timeout=timeout)
    try:
        control.stop()
    except Exception:
        pass

    if not got:
        return None
    return result["image"]
