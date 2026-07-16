"""
Game automation: visually finds and clicks Warframe UI buttons.

KEY DISCOVERY: Warframe (DirectX) ignores SendInput absolute coords.
The only reliable method is:
  1. win32api.SetCursorPos(x, y)   — physically move the HW cursor
  2. win32api.mouse_event(DOWN/UP, 0, 0)  — fire at current cursor pos

Also: our app window must be minimized before activating Warframe,
otherwise Qt steals focus back between activate and click.
"""

import ctypes
import time

import win32api
import win32con
import win32gui

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP   = 0x0004
MOUSEEVENTF_RIGHTUP  = 0x0010
VK_MENU              = 0x12
VK_CONTROL           = 0x11
VK_SHIFT             = 0x10
KEYEVENTF_KEYUP      = 0x0002

# Virtual key codes for keyboard input
VK_RETURN = 0x0D   # Enter — confirms YES on any dialog
VK_N      = 0x4E   # N key — Warframe uses N to go back / pick NO
VK_E      = 0x45   # E key — Warframe uses E to interact / confirm YES

_user32  = ctypes.windll.user32
_wf_hwnd: int = 0
_app_hwnds: list[int] = []   # our own Qt windows, cached


# ── Window helpers ──────────────────────────────────────────────────────────

def _get_wf_hwnd() -> int:
    global _wf_hwnd
    if _wf_hwnd:
        try:
            if win32gui.IsWindow(_wf_hwnd):
                return _wf_hwnd
        except Exception:
            pass
    _wf_hwnd = win32gui.FindWindow(None, "Warframe")
    return _wf_hwnd


def _find_app_hwnds() -> list[int]:
    """Find all our own Qt windows so we can minimize them."""
    results = []
    def cb(hwnd, _):
        title = win32gui.GetWindowText(hwnd)
        if "WF Riven" in title or "Riven Roller" in title:
            results.append(hwnd)
    win32gui.EnumWindows(cb, None)
    return results


def _foreground_is_user_elsewhere(wf_hwnd: int) -> bool:
    """
    True when the user has deliberately switched to some OTHER application
    (a browser, Discord, the taskbar, etc.) — i.e. the foreground window is
    neither Warframe nor one of our own windows.

    The roller uses this to PAUSE instead of yanking focus back. Stealing
    focus every cycle was the alt-tab lockout: the moment you switched away,
    the next roll dragged you back into the game.
    """
    fg = win32gui.GetForegroundWindow()
    if not fg or fg == wf_hwnd:
        return False
    if fg in _find_app_hwnds():
        return False   # our own window — fine to proceed (start-of-session)
    return True


def activate_warframe() -> bool:
    """
    Ensure Warframe is the foreground window so clicks land on it.

    Returns:
      True  — Warframe is foreground and ready to be clicked.
      False — the user has switched to another app; we did NOT steal focus.
              The caller should pause and retry, not click.

    Behavior:
      - If Warframe is already foreground, do nothing (no minimize, no
        alt-key trick, no SetForegroundWindow). This removes the per-cycle
        focus thrash that fought the user and could leave ALT stuck.
      - If the user is in another app, return False without touching focus.
      - Only when the foreground is our own window (session start) do we
        minimize ourselves and bring Warframe forward.
    """
    hwnd = _get_wf_hwnd()
    if not hwnd:
        return False

    if win32gui.GetForegroundWindow() == hwnd:
        return True   # already focused — nothing to do, don't thrash focus

    if _foreground_is_user_elsewhere(hwnd):
        return False  # user is elsewhere on purpose — pause, never steal

    # Foreground is our own window (or desktop): OK to bring Warframe forward.
    for h in _find_app_hwnds():
        try:
            win32gui.ShowWindow(h, win32con.SW_MINIMIZE)
        except Exception:
            pass

    time.sleep(0.15)

    # Alt-key unlock trick then SetForegroundWindow. Guaranteed ALT release
    # via finally so a stuck modifier can't wedge the taskbar afterwards.
    try:
        _user32.keybd_event(VK_MENU, 0, 0, 0)
        _user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.05)
        _user32.SetForegroundWindow(hwnd)
        time.sleep(0.3)
    finally:
        _user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)

    return win32gui.GetForegroundWindow() == hwnd


def _click(x: int, y: int):
    """
    The ONLY click method that works with Warframe:
    SetCursorPos (physical move) then mouse_event with relative coords.
    """
    win32api.SetCursorPos((x, y))
    time.sleep(0.08)   # let game register cursor position
    win32api.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.06)
    win32api.mouse_event(MOUSEEVENTF_LEFTUP,   0, 0, 0, 0)


def _park_cursor():
    """
    Move cursor to top-left corner (away from any UI buttons) so it doesn't
    interfere with OCR reading button text. Call before any OCR scan.
    """
    win32api.SetCursorPos((10, 10))


def _press_key(vk: int):
    """
    Send a keyboard key press+release to the foreground window (Warframe).
    Works with Warframe's DirectX input — uses keybd_event which fires
    at the hardware level, same as the cursor move trick for mouse.
    """
    _user32.keybd_event(vk, 0, 0, 0)              # key down
    time.sleep(0.06)
    _user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)  # key up
    time.sleep(0.05)


# ── Interruptible sleep ─────────────────────────────────────────────────────

def release_input_state() -> None:
    """
    Best-effort cleanup for emergency stop and failure paths.

    If automation exits while Windows or Warframe believes a modifier or mouse
    button is still down, Alt-Tab and focus behavior can feel broken until the
    user presses that key/button again. Releasing these inputs is harmless when
    they are already up and gives control back faster.
    """
    for vk in (VK_MENU, VK_CONTROL, VK_SHIFT):
        try:
            _user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        except Exception:
            pass
    try:
        win32api.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        win32api.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
    except Exception:
        pass


def _interruptible_sleep(seconds: float, stop_flag=None) -> bool:
    """Sleep in 0.1s chunks. Returns True immediately if stop_flag is set."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if stop_flag is not None and stop_flag.is_set():
            return True
        time.sleep(min(0.1, end - time.monotonic()))
    return False


# ── Visual click: find text on screen then click it ────────────────────────

def _ocr_all_text() -> list[dict]:
    """
    OCR the screen once. Returns list of {text, cx, cy} for every line found.
    Parks cursor at top-left first so it doesn't cover button text.
    """
    import winocr
    from core.capture import grab_frame
    _park_cursor()           # move cursor away from UI before screenshot
    time.sleep(0.05)         # brief settle so cursor move registers
    frame  = grab_frame()
    result = winocr.recognize_pil_sync(frame, "en")
    items  = []
    for line in result.get("lines", []):
        text = line.get("text", "").strip()
        if not text:
            continue
        words = line.get("words", [])
        if not words:
            continue
        xs  = [w["bounding_rect"]["x"]      for w in words if "bounding_rect" in w]
        ys  = [w["bounding_rect"]["y"]      for w in words if "bounding_rect" in w]
        ws2 = [w["bounding_rect"]["width"]  for w in words if "bounding_rect" in w]
        hs2 = [w["bounding_rect"]["height"] for w in words if "bounding_rect" in w]
        if not xs:
            continue
        cx = int((min(xs) + max(x + w for x, w in zip(xs, ws2))) / 2)
        cy = int((min(ys) + max(y + h for y, h in zip(ys, hs2))) / 2)
        items.append({"text": text, "cx": cx, "cy": cy})
    return items


def _find_on_screen(keyword: str,
                    require_also: str | None = None,
                    exclude_if: str | None = None) -> tuple[int, int] | None:
    """
    OCR the screen once and return center (x,y) of first line containing keyword.

    require_also : if set, the keyword is only matched when another line on
                   screen also contains this string (confirms we're on the right dialog).
    exclude_if   : if set, skip the match when another line contains this string
                   (guards against clicking YES on the wrong dialog).
    """
    items = _ocr_all_text()
    texts = [i["text"].lower() for i in items]

    # Context guards
    if require_also and not any(require_also.lower() in t for t in texts):
        return None
    if exclude_if and any(exclude_if.lower() in t for t in texts):
        return None

    kw = keyword.lower()
    for item in items:
        if kw in item["text"].lower():
            return item["cx"], item["cy"]
    return None


def _visual_click(keyword: str, stop_flag=None, timeout: float = 10.0,
                  require_also: str | None = None,
                  exclude_if:   str | None = None) -> bool:
    """
    Poll screen with OCR until `keyword` is found, then click it.
    Waits up to `timeout` seconds. Returns True if stop_flag set.
    Raises RuntimeError if button never appears.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if stop_flag and stop_flag.is_set():
            return True
        pos = _find_on_screen(keyword, require_also=require_also,
                               exclude_if=exclude_if)
        if pos:
            _click(pos[0], pos[1])
            return False
        time.sleep(0.35)

    raise RuntimeError(
        f"Could not find '{keyword}' on screen within {timeout:.0f}s.\n"
        f"Make sure Warframe is visible and on the correct screen."
    )


# ── Public rolling API ───────────────────────────────────────────────────────

def press_cycle(stop_flag=None) -> bool:
    """
    Step 1: ensure Warframe has focus, then click CYCLE FOR KUVA.

    If the user has alt-tabbed to another app, PAUSE here (polling, never
    stealing focus) until they return to Warframe — or press stop. This is
    what lets you leave the game while a session is 'running' instead of
    being dragged back every roll.
    """
    paused = False
    while True:
        if stop_flag is not None and stop_flag.is_set():
            return True
        if activate_warframe():
            if paused:
                _log_note("Resumed — Warframe is focused again.")
            break
        # User is in another app on purpose — wait and re-check. We do not
        # click and do not steal focus while paused. Log once so an apparent
        # "hang" is visibly a deliberate pause in diagnostics.
        if not paused:
            paused = True
            _log_note("PAUSED — Warframe is not the focused window; click back "
                      "into the game (or press stop) to resume rolling.")
        if _interruptible_sleep(0.6, stop_flag):
            return True
    return _visual_click("CYCLE FOR", stop_flag)


def _log_note(message: str) -> None:
    try:
        from core import roll_logger
        roll_logger.log_note(message)
    except Exception:
        pass


def _click_yes_on_dialog(stop_flag=None, timeout: float = 10.0) -> bool:
    """
    Wait for a YES/NO dialog, then click the YES button directly.
    Finds the YES text via OCR and clicks its exact screen coordinates.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if stop_flag and stop_flag.is_set():
            return True
        items = _ocr_all_text()
        # Find the item whose text IS exactly YES (case-insensitive, strip punctuation)
        yes_item = None
        no_item  = None
        for i in items:
            clean = i["text"].strip().rstrip(".,!").upper()
            if clean == "YES":
                yes_item = i
            elif clean == "NO":
                no_item = i
        # Only click when BOTH buttons are visible (confirms dialog is fully shown)
        if yes_item and no_item:
            _click(yes_item["cx"], yes_item["cy"])
            return False
        time.sleep(0.3)
    raise RuntimeError(
        f"Could not find YES button on screen within {timeout:.0f}s.\n"
        "Make sure Warframe is showing a YES/NO dialog."
    )


def _click_no_on_dialog(stop_flag=None, timeout: float = 10.0) -> bool:
    """
    Wait for a YES/NO dialog, then click the NO button directly.
    Finds the NO text via OCR and clicks its exact screen coordinates.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if stop_flag and stop_flag.is_set():
            return True
        items = _ocr_all_text()
        yes_item = None
        no_item  = None
        for i in items:
            clean = i["text"].strip().rstrip(".,!").upper()
            if clean == "YES":
                yes_item = i
            elif clean == "NO":
                no_item = i
        if yes_item and no_item:
            _click(no_item["cx"], no_item["cy"])
            return False
        time.sleep(0.3)
    raise RuntimeError(
        f"Could not find NO button on screen within {timeout:.0f}s.\n"
        "Make sure Warframe is showing a YES/NO dialog."
    )


def click_cycle_yes(stop_flag=None) -> bool:
    """Step 2: Click YES on the kuva-spend 'Are you sure?' dialog."""
    return _click_yes_on_dialog(stop_flag)


def wait_for_animation(seconds: float = 2.5, stop_flag=None) -> bool:
    return _interruptible_sleep(seconds, stop_flag)


def click_confirm(stop_flag=None) -> bool:
    """Step 5: Click CONFIRM button in the two-card view."""
    return _visual_click("CONFIRM", stop_flag)


def click_keep_yes(stop_flag=None) -> bool:
    """Step 6a: Click YES — keep the new roll."""
    return _click_yes_on_dialog(stop_flag)


def click_keep_no(stop_flag=None) -> bool:
    """Step 6b: Click NO — revert to the old roll."""
    return _click_no_on_dialog(stop_flag)


def wait_for_dialog(seconds: float = 0.6, stop_flag=None) -> bool:
    return _interruptible_sleep(seconds, stop_flag)


def revert_roll(stop_flag=None, new_parsed=None) -> bool:
    """
    Reject the new roll by selecting the OLD (left) card, then confirming it.

    Verified from live compare captures (1920x1080): the new roll is the
    bright/selected card at ~50% x; the equipped riven is the DIMMED card on
    the LEFT at ~36% x / ~57% y. Clicking that left card promotes it to the
    centre (selected) and moves CONFIRM beneath it — screenshot-confirmed.

      Step 1: Click the LEFT card (old riven, fixed 36% x / 57% y)
      Step 2: Click CONFIRM  (OCR-located — now under the old card)
      Step 3: Click YES      → old riven kept, back to CYCLE FOR

    No CONFIRM→NO. The click position is a fixed, verified coordinate (not the
    OCR-detected one, which can point at the new card), so this reliably keeps
    the old riven. ``new_parsed`` is accepted for compatibility but unused.

    Returns True if stop_flag was set (caller should break).
    """
    # Minimize app so it can't cover Warframe's UI
    for hwnd in _find_app_hwnds():
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
        except Exception:
            pass
    time.sleep(0.2)

    from core.capture import grab_frame
    frame = grab_frame()
    w, h = frame.size

    # ── Step 1: click the LEFT (old) card to select it ───────────────────────
    _click(int(w * 0.358), int(h * 0.57))
    time.sleep(0.6)  # let the selection move to the old card

    # ── Step 2: click CONFIRM (OCR-located, now under the old card) ──────────
    if _visual_click("CONFIRM", stop_flag, timeout=10.0):
        return True
    time.sleep(0.5)

    # ── Step 3: click YES (confirm keeping the old riven) ────────────────────
    if _click_yes_on_dialog(stop_flag, timeout=10.0):
        return True
    time.sleep(0.4)

    # ── Wait for CYCLE FOR (cycling screen ready) ────────────────────────────
    deadline = time.monotonic() + 12.0
    while time.monotonic() < deadline:
        if stop_flag and stop_flag.is_set():
            return True
        if _find_on_screen("CYCLE FOR"):
            time.sleep(0.25)
            return False
        time.sleep(0.4)

    return False  # timed out gracefully — press_cycle will re-poll


def wait_for_screen_settle(stop_flag=None, after_revert: bool = False) -> bool:
    """
    After clicking YES (keep new roll), wait for CYCLE FOR to appear.
    For the revert path use revert_roll() instead.

    Minimizes app first so it can't cover Warframe's UI during OCR polling.
    """
    # Minimize app so it doesn't block Warframe's UI from OCR
    for h in _find_app_hwnds():
        try:
            win32gui.ShowWindow(h, win32con.SW_MINIMIZE)
        except Exception:
            pass
    time.sleep(0.2)

    deadline = time.monotonic() + 12.0
    while time.monotonic() < deadline:
        if stop_flag and stop_flag.is_set():
            return True
        if _find_on_screen("CYCLE FOR"):
            time.sleep(0.25)
            return False
        # Safety: if CONFIRM appears unexpectedly, click it
        items = _ocr_all_text()
        for i in items:
            if i["text"].strip().upper() == "CONFIRM":
                _click(i["cx"], i["cy"])
                time.sleep(0.6)
                break
        time.sleep(0.4)
    return False  # timed out gracefully


# ── Legacy compat ────────────────────────────────────────────────────────────
_DEFAULTS = {}
_coords: dict = {}
def load_coords(config: dict): pass
def get_coords() -> dict: return {}
def update_coord(key: str, x: int, y: int): pass
