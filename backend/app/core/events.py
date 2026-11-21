"""In-process pub/sub for live progress (ADR-0010). Subscribers receive a notification that a
topic changed and re-read its state; messages carry no payload, so nothing can be lost or stale."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[None]]] = defaultdict(set)

    def publish(self, topic: str) -> None:
        for queue in list(self._subscribers.get(topic, ())):
            if queue.empty():  # coalesce bursts: one pending notification is enough
                queue.put_nowait(None)

    @asynccontextmanager
    async def subscribe(self, topic: str) -> AsyncIterator[asyncio.Queue[None]]:
        queue: asyncio.Queue[None] = asyncio.Queue(maxsize=1)
        self._subscribers[topic].add(queue)
        try:
            yield queue
        finally:
            self._subscribers[topic].discard(queue)
            if not self._subscribers[topic]:
                del self._subscribers[topic]
