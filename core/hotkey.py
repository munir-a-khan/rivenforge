"""
Global hotkey listener (Windows).

Uses the Win32 ``RegisterHotKey`` API so the hotkey fires even while
Warframe has focus and we are programmatically moving the mouse — the
GUI Stop button is unreachable in that state because any user mouse
movement collides with the automation.

The listener pumps messages on its own background thread; the supplied
callback runs on that thread, so callers must bounce to the GUI thread
themselves (e.g. via a Qt signal).
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable

WM_HOTKEY = 0x0312
WM_QUIT   = 0x0012

MOD_ALT     = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT   = 0x0004
MOD_WIN     = 0x0008
MOD_NOREPEAT = 0x4000   # don't auto-repeat while held

# Virtual-key codes for the default hotkey: Ctrl + Shift + Q
VK_Q = 0x51

DEFAULT_MODIFIERS = MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT
DEFAULT_VK        = VK_Q
DEFAULT_LABEL     = "Ctrl+Shift+Q"


class HotkeyListener:
    """Run a tiny Win32 message pump that fires ``on_pressed`` on each hit."""

    def __init__(
        self,
        on_pressed: Callable[[], None],
        modifiers: int = DEFAULT_MODIFIERS,
        vk: int = DEFAULT_VK,
        label: str = DEFAULT_LABEL,
    ):
        self._on_pressed = on_pressed
        self._modifiers  = modifiers
        self._vk         = vk
        self.label       = label
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._hotkey_id  = 1
        self._ready      = threading.Event()
        self._registered = False

    def start(self) -> bool:
        """Spin up the listener thread. Returns True if the hotkey registered."""
        if self._thread and self._thread.is_alive():
            return self._registered
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._run, name="HotkeyListener", daemon=True
        )
        self._thread.start()
        # Wait briefly for RegisterHotKey to succeed/fail so callers know.
        self._ready.wait(timeout=2.0)
        return self._registered

    def stop(self) -> None:
        if self._thread_id is not None:
            # Wake GetMessageW so the pump can exit.
            ctypes.windll.user32.PostThreadMessageW(
                self._thread_id, WM_QUIT, 0, 0
            )
        if self._thread:
            self._thread.join(timeout=1.0)
        self._thread = None
        self._thread_id = None
        self._registered = False

    def _run(self) -> None:
        user32   = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        self._thread_id  = kernel32.GetCurrentThreadId()
        self._registered = bool(user32.RegisterHotKey(
            None, self._hotkey_id, self._modifiers, self._vk
        ))
        self._ready.set()
        if not self._registered:
            return

        try:
            msg = wintypes.MSG()
            while True:
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret in (0, -1):  # WM_QUIT or error
                    break
                if msg.message == WM_HOTKEY and msg.wParam == self._hotkey_id:
                    try:
                        self._on_pressed()
                    except Exception:
                        pass
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            user32.UnregisterHotKey(None, self._hotkey_id)
            self._registered = False
