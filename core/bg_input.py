"""
Background input via Win32 PostMessage — no focus steal, no cursor move.

This is the *documented* way to send mouse/keyboard input to a specific
window without bringing it to the foreground and without moving the user's
real hardware cursor. It posts standard window messages
(``WM_LBUTTONDOWN``, ``WM_KEYDOWN``, …) to the target's message queue.

    Screen coords ──(ScreenToClient)──▶ client coords ──▶ lParam ──▶ PostMessage

Explicitly NOT here: DLL injection, input drivers, raw-input synthesis, or
stealth/anti-cheat evasion. This is plain user32 messaging — the same thing
accessibility tools and UI test frameworks use.

The open question this module exists to answer: **does Warframe's riven UI
honor posted messages?** DirectX titles frequently read RawInput/DirectInput
for gameplay and ignore ``WM_*`` messages, but menu/UI screens often still
process them. `probe_target` sends a non-destructive hover and captures
before/after frames so the caller can decide empirically. If posting does
NOT register, the documented boundary is: background *capture* works,
background *input* does not, and rolling stays foreground-only.
"""

from __future__ import annotations

import time
from typing import Any

try:
    import win32api
    import win32gui
    HAS_WIN32 = True
except ImportError:  # pragma: no cover - platform guard
    HAS_WIN32 = False

# Window message constants (from WinUser.h).
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SETCURSOR = 0x0020
MK_LBUTTON = 0x0001


def is_available() -> bool:
    """True if PostMessage-based input can be attempted on this machine."""
    return HAS_WIN32


def _lparam(x: int, y: int) -> int:
    """Pack client coords into an lParam (low word = x, high word = y)."""
    return ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)


def screen_to_client(hwnd: int, sx: int, sy: int) -> tuple[int, int]:
    """Convert absolute screen coords to window-client coords for ``hwnd``."""
    if not HAS_WIN32:
        return int(sx), int(sy)
    cx, cy = win32gui.ScreenToClient(hwnd, (int(sx), int(sy)))
    return int(cx), int(cy)


def post_mouse_move(hwnd: int, cx: int, cy: int) -> bool:
    """
    Post a mouse-move to ``hwnd`` at client coords (cx, cy). Non-destructive:
    triggers hover states without clicking. Returns True if the message was
    posted (not whether the target acted on it).
    """
    if not HAS_WIN32 or not hwnd:
        return False
    lp = _lparam(cx, cy)
    try:
        win32api.PostMessage(hwnd, WM_MOUSEMOVE, 0, lp)
        return True
    except Exception:
        return False


def post_click(hwnd: int, cx: int, cy: int, settle: float = 0.05) -> bool:
    """
    Post a left click to ``hwnd`` at client coords (cx, cy) with no focus
    steal and no real-cursor movement.

    Sequence mirrors a real click: move → button-down (with MK_LBUTTON
    held) → button-up. Returns True if all messages posted. Whether the
    target *acts* on them is what `probe_target` is for.
    """
    if not HAS_WIN32 or not hwnd:
        return False
    lp = _lparam(cx, cy)
    try:
        win32api.PostMessage(hwnd, WM_MOUSEMOVE, 0, lp)
        time.sleep(settle)
        win32api.PostMessage(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lp)
        time.sleep(settle)
        win32api.PostMessage(hwnd, WM_LBUTTONUP, 0, lp)
        return True
    except Exception:
        return False


def post_click_screen(hwnd: int, sx: int, sy: int, settle: float = 0.05) -> bool:
    """Post a left click given absolute screen coords (converted to client)."""
    cx, cy = screen_to_client(hwnd, sx, sy)
    return post_click(hwnd, cx, cy, settle=settle)


def post_key(hwnd: int, vk: int, settle: float = 0.04) -> bool:
    """
    Post a key press+release (virtual-key code ``vk``) to ``hwnd`` without
    focusing it. Returns True if both messages posted.
    """
    if not HAS_WIN32 or not hwnd:
        return False
    try:
        win32api.PostMessage(hwnd, WM_KEYDOWN, int(vk), 0)
        time.sleep(settle)
        win32api.PostMessage(hwnd, WM_KEYUP, int(vk), 0)
        return True
    except Exception:
        return False


def probe_target(hwnd: int, cx: int, cy: int) -> dict[str, Any]:
    """
    Non-destructive probe: post a hover-move to (cx, cy) and report what was
    done. Does NOT click, so it never rolls a riven or spends kuva.

    The caller is expected to capture a frame before and after (via the WGC
    backend) and eyeball whether a hover highlight appeared — that is the
    empirical yes/no on whether PostMessage input registers with Warframe's
    UI. We deliberately don't auto-click a live button here.
    """
    result: dict[str, Any] = {
        "available": HAS_WIN32,
        "hwnd": int(hwnd) if hwnd else None,
        "posted_move": False,
        "client_coords": [int(cx), int(cy)],
        "notes": [],
    }
    if not HAS_WIN32:
        result["notes"].append("pywin32 unavailable; cannot post messages.")
        return result
    if not hwnd:
        result["notes"].append("No target hwnd; is Warframe running?")
        return result

    result["posted_move"] = post_mouse_move(hwnd, cx, cy)
    if result["posted_move"]:
        result["notes"].append(
            "Hover posted. Compare before/after frames: if a button highlight "
            "appears, Warframe honors posted messages and background input is "
            "viable. If nothing changes, background clicks will not register "
            "and rolling must stay foreground-only."
        )
    else:
        result["notes"].append("PostMessage failed; check the hwnd is valid.")
    return result
