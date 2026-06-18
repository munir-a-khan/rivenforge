from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any


@dataclass
class _Subscriber:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[dict[str, Any]]


@dataclass
class EventBus:
    """Small in-process event bus for REST callbacks and WebSocket clients."""

    def __init__(self) -> None:
        self._subscribers: list[_Subscriber] = []

    async def publish(self, event: dict[str, Any]) -> None:
        stale: list[_Subscriber] = []
        for subscriber in list(self._subscribers):
            try:
                subscriber.queue.put_nowait(event)
            except asyncio.QueueFull:
                stale.append(subscriber)
        for subscriber in stale:
            self._discard(subscriber)

    def publish_threadsafe(self, event: dict[str, Any]) -> None:
        for subscriber in list(self._subscribers):
            subscriber.loop.call_soon_threadsafe(subscriber.queue.put_nowait, event)

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        subscriber = _Subscriber(loop=loop, queue=queue)
        self._subscribers.append(subscriber)
        try:
            while True:
                yield await queue.get()
        finally:
            self._discard(subscriber)

    def _discard(self, subscriber: _Subscriber) -> None:
        try:
            self._subscribers.remove(subscriber)
        except ValueError:
            pass


event_bus = EventBus()
