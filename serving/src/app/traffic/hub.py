"""Fan-out of analysis events inside the API replica.

However many browsers are connected, the API replica asks the traffic deployment for
new events once; every connection gets a copy from a queue of its own.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any

log = logging.getLogger("ray.serve")

Batch = list[dict[str, Any]]
# Long-poll: returns {"latest": int, "events": [...]} for events after the given number.
Fetch = Callable[[int], Awaitable[dict[str, Any]]]


class TooManySubscribersError(Exception):
    pass


class EventHub:
    QUEUE_SIZE = 64  # batches; a connection that falls further behind loses the oldest

    def __init__(self, fetch: Fetch, max_subscribers: int, retry_seconds: float = 1.0) -> None:
        self._fetch = fetch
        self._max_subscribers = max_subscribers
        self._retry_seconds = retry_seconds
        self._queues: set[asyncio.Queue[Batch]] = set()
        self._task: asyncio.Task[None] | None = None
        self._seq: int | None = None

    @property
    def subscribers(self) -> int:
        return len(self._queues)

    async def subscribe(self, heartbeat_seconds: float = 10.0) -> AsyncGenerator[Batch]:
        """Batches of events as they arrive; an empty batch when nothing happened for
        ``heartbeat_seconds`` (so the caller can keep its connection alive)."""
        if len(self._queues) >= self._max_subscribers:
            raise TooManySubscribersError
        queue: asyncio.Queue[Batch] = asyncio.Queue(self.QUEUE_SIZE)
        self._queues.add(queue)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._pump())
        try:
            while True:
                try:
                    yield await asyncio.wait_for(queue.get(), heartbeat_seconds)
                except TimeoutError:
                    yield []
        finally:
            self._queues.discard(queue)

    async def _pump(self) -> None:
        while self._queues:
            try:
                # A new connection starts with what happens from now on (None: skip the
                # backlog); a restarted traffic deployment counts from zero again.
                answer = await self._fetch(self._seq if self._seq is not None else 2**62)
                latest = int(answer["latest"])
                if self._seq is None or latest < self._seq:
                    self._seq = latest if self._seq is None else 0
                    continue
                self._seq = latest
                events: Batch = answer["events"]
            except Exception:
                log.exception("fetching traffic events failed")
                await asyncio.sleep(self._retry_seconds)
                continue
            if not events:
                continue
            for queue in self._queues:
                if queue.full():
                    queue.get_nowait()
                queue.put_nowait(events)
        self._seq = None
