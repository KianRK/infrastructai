"""In-process, per-key rate limiting (sliding window).

State lives in the API replica's memory, so the limits are exact only with a single API
replica; with N replicas a client can get up to N times the limit. That is acceptable for
this demo (one replica, and the gateway enforces its own limit in front), and is why the
limiter is a small class that could be swapped for a shared store.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from app.settings import RateLimit


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after: float  # seconds until the next request would be allowed; 0 if allowed


class SlidingWindowLimiter:
    def __init__(
        self,
        config: RateLimit,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 10_000,
    ) -> None:
        self._limit = config.limit
        self._window = config.window_seconds
        self._clock = clock
        self._max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str) -> Decision:
        """Record a request for ``key`` if it is within the limit."""
        now = self._clock()
        hits = self._hits.get(key)
        if hits is None:
            if len(self._hits) >= self._max_keys:
                self._prune(now)
            hits = self._hits[key] = deque()
        cutoff = now - self._window
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= self._limit:
            return Decision(False, hits[0] + self._window - now)
        hits.append(now)
        return Decision(True, 0.0)

    def _prune(self, now: float) -> None:
        """Bound memory: forget idle keys; if all are active, forget the oldest ones."""
        cutoff = now - self._window
        self._hits = {k: v for k, v in self._hits.items() if v and v[-1] > cutoff}
        if len(self._hits) >= self._max_keys:
            oldest = sorted(self._hits, key=lambda k: self._hits[k][-1])
            for key in oldest[: len(oldest) // 2]:
                del self._hits[key]

    def __len__(self) -> int:
        return len(self._hits)
