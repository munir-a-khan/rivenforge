from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from api.events import event_bus
from core.roller import RollerThread


@dataclass
class RollSession:
    session_id: str
    thread: RollerThread


class RollSessionManager:
    def __init__(self) -> None:
        self._session: RollSession | None = None
        # Snapshot of the params the active session was started with, so a
        # phone joining mid-session (via GET /roll/session) can show what is
        # running. The WebSocket only streams NEW roll events.
        self._last_payload: dict[str, Any] = {}

    def snapshot(self) -> dict[str, Any]:
        """A phone-friendly view of the current session (running or not)."""
        running = bool(self._session and self._session.thread.is_alive())
        p = self._last_payload if running else {}
        return {
            "running": running,
            "session_id": self._session.session_id if (running and self._session) else None,
            "weapon": p.get("weapon", ""),
            "weapon_type": p.get("weapon_type", ""),
            "roll_limit": p.get("roll_limit", 0),
            "roll_until_match": p.get("roll_until_match", False),
        }

    def start(self, payload: dict[str, Any]) -> str:
        if self._session and self._session.thread.is_alive():
            raise RuntimeError("A roll session is already running.")

        session_id = str(uuid.uuid4())
        self._last_payload = dict(payload)

        thread = RollerThread(
            weapon=payload["weapon"],
            weapon_type=payload["weapon_type"],
            profiles=payload["profiles"],
            roll_limit=payload.get("roll_limit", 100),
            rag_threshold=payload.get("rag_threshold", 0.6),
            animation_wait=payload.get("animation_wait", 2.5),
            stat_priority=payload.get("stat_priority", []),
            neg_priority=payload.get("neg_priority", []),
            roll_until_match=payload.get("roll_until_match", False),
            confirm_reads=payload.get("confirm_reads", 3),
            on_roll=lambda roll_num, parsed, rule_result, rag_result, accepted: event_bus.publish_threadsafe({
                "kind": "roll",
                "session_id": session_id,
                "roll_num": roll_num,
                "parsed": parsed,
                "rule_result": rule_result,
                "rag_result": rag_result,
                "accepted": accepted,
            }),
            on_done=lambda reason: event_bus.publish_threadsafe({
                "kind": "done",
                "session_id": session_id,
                "reason": reason,
            }),
            on_error=lambda message: event_bus.publish_threadsafe({
                "kind": "error",
                "session_id": session_id,
                "message": message,
            }),
        )
        self._session = RollSession(session_id=session_id, thread=thread)
        thread.start()
        return session_id

    def stop(self) -> bool:
        if not self._session:
            return False
        self._session.thread.stop()
        try:
            from core.automation import release_input_state
            release_input_state()
        except Exception:
            pass
        return True

    def active_session_id(self) -> str | None:
        if self._session and self._session.thread.is_alive():
            return self._session.session_id
        return None


session_manager = RollSessionManager()
