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

    def start(self, payload: dict[str, Any]) -> str:
        if self._session and self._session.thread.is_alive():
            raise RuntimeError("A roll session is already running.")

        session_id = str(uuid.uuid4())

        thread = RollerThread(
            weapon=payload["weapon"],
            weapon_type=payload["weapon_type"],
            profiles=payload["profiles"],
            roll_limit=payload.get("roll_limit", 100),
            rag_threshold=payload.get("rag_threshold", 0.6),
            animation_wait=payload.get("animation_wait", 2.5),
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
        return True

    def active_session_id(self) -> str | None:
        if self._session and self._session.thread.is_alive():
            return self._session.session_id
        return None


session_manager = RollSessionManager()
