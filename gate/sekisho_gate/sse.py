"""In-process pub/sub for GET /v1/stream (docs/api.md, SSE).

Every published message gets an increasing integer id. Each subscriber has its own
bounded queue; a slow subscriber loses its oldest messages rather than blocking the
gate. The last messages are kept so a reconnecting client can resume with
Last-Event-ID. Keep-alive comments are sent by sse-starlette (ping every 15 s).
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import dataclass
from typing import Any, AsyncIterator

EVENTS = ("case.created", "case.updated", "chain.event", "metrics.updated")
KEEPALIVE_S = 15


@dataclass(frozen=True)
class Message:
    id: int
    event: str
    data: str  # JSON text

    def as_sse(self) -> dict[str, str]:
        return {"id": str(self.id), "event": self.event, "data": self.data}


class Broker:
    def __init__(self, queue_size: int = 256, replay_size: int = 500):
        self._next_id = 1
        self._subscribers: set[asyncio.Queue[Message]] = set()
        self._recent: deque[Message] = deque(maxlen=replay_size)
        self._queue_size = queue_size

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @property
    def last_id(self) -> int:
        return self._next_id - 1

    def publish(self, event: str, data: Any) -> Message:
        msg = Message(self._next_id, event, json.dumps(data, ensure_ascii=False, default=str))
        self._next_id += 1
        self._recent.append(msg)
        for q in list(self._subscribers):
            if q.full():
                try:
                    q.get_nowait()  # drop the oldest for this slow subscriber
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(msg)
        return msg

    def subscribe(self, last_event_id: int | None = None) -> asyncio.Queue[Message]:
        q: asyncio.Queue[Message] = asyncio.Queue(maxsize=self._queue_size)
        if last_event_id is not None:
            for msg in self._recent:
                if msg.id > last_event_id and not q.full():
                    q.put_nowait(msg)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Message]) -> None:
        self._subscribers.discard(q)

    async def stream(self, last_event_id: int | None = None) -> AsyncIterator[dict[str, str]]:
        """Yields sse-starlette event dicts until the client goes away."""
        q = self.subscribe(last_event_id)
        try:
            while True:
                msg = await q.get()
                yield msg.as_sse()
        finally:
            self.unsubscribe(q)


def parse_last_event_id(value: str | None) -> int | None:
    try:
        return int(value) if value is not None and value.strip() else None
    except ValueError:
        return None
