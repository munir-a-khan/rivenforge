"""
Regression: a transient mid-roll UI hiccup must NOT end the session.

Before this, any button that OCR-timed-out raised RuntimeError straight out of
the roll loop and killed the whole run ("rolls fine then stops out of nowhere").
Now a hiccup is caught, recovery is attempted, and only MAX_CONSECUTIVE_HICCUPS
back-to-back failures end the session — via on_done with a clear reason, never
on_error.
"""

from __future__ import annotations

import pytest

# The roller pulls Windows-only capture/vision deps in when run() executes.
pytest.importorskip("win32gui")
pytest.importorskip("cv2")


def test_transient_hiccup_does_not_kill_session_and_stops_cleanly(monkeypatch):
    from core import automation, roller

    calls = {"press": 0, "recover": 0}

    def boom(sf=None):
        calls["press"] += 1
        raise RuntimeError("Could not find 'CONFIRM' on screen within 8s.")

    def fake_recover(sf=None, timeout=20.0):
        calls["recover"] += 1
        return False  # not stopped; pretend we got back to the cycle screen

    monkeypatch.setattr(automation, "press_cycle", boom)
    monkeypatch.setattr(automation, "recover_to_cycle", fake_recover)

    done: list[str] = []
    errors: list[str] = []

    t = roller.RollerThread(
        weapon="Test",
        weapon_type="primary",
        profiles=[],
        roll_limit=0,  # no roll cap — only the hiccup budget should stop us
        confirm_reads=1,
        on_done=done.append,
        on_error=errors.append,
    )
    t.run()  # synchronous — exercise the loop directly

    # A transient hiccup must never surface as a fatal error.
    assert errors == []
    # Session ends cleanly, once, explaining why.
    assert len(done) == 1
    assert "consecutive UI hiccups" in done[0]
    # It retried up to the budget: press fires MAX times, recovery MAX-1 times
    # (the final failure finishes before recovering).
    assert calls["press"] == roller.MAX_CONSECUTIVE_HICCUPS
    assert calls["recover"] == roller.MAX_CONSECUTIVE_HICCUPS - 1


def test_stop_requested_during_recovery_ends_without_error(monkeypatch):
    from core import automation, roller

    def boom(sf=None):
        raise RuntimeError("Could not find YES button on screen within 10s.")

    def recover_sees_stop(sf=None, timeout=20.0):
        return True  # a stop was requested mid-recovery

    monkeypatch.setattr(automation, "press_cycle", boom)
    monkeypatch.setattr(automation, "recover_to_cycle", recover_sees_stop)

    done: list[str] = []
    errors: list[str] = []

    t = roller.RollerThread(
        weapon="Test",
        weapon_type="primary",
        profiles=[],
        roll_limit=0,
        confirm_reads=1,
        on_done=done.append,
        on_error=errors.append,
    )
    t.stop()  # ask to stop up front; recovery reports it
    t.run()

    assert errors == []
    assert len(done) == 1
    assert "Stopped" in done[0]
