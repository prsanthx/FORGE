"""In-process pub/sub for server-sent run events."""

from __future__ import annotations

import asyncio
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue]] = {}

    def subscribe(self, run_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subs.setdefault(run_id, []).append(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue) -> None:
        subs = self._subs.get(run_id, [])
        if queue in subs:
            subs.remove(queue)

    def publish(self, run_id: str, event: dict[str, Any]) -> None:
        for queue in list(self._subs.get(run_id, [])):
            queue.put_nowait(event)
