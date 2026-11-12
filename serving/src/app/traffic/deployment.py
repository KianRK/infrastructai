"""Traffic deployment: owns the stream clock, the detector and the analysis loop.

It must run as a single replica: every replica would have its own clock and counters.
"""

from __future__ import annotations

import time
from typing import Any

from ray import serve

from app.settings import TrafficArgs
from app.traffic.pipeline import TrafficService, build_workers


@serve.deployment
class Traffic:
    def __init__(self, args: TrafficArgs) -> None:
        workers, backend = build_workers(args, epoch=time.time())
        self._service = TrafficService(args, workers, backend)

    async def describe(self) -> dict[str, Any]:
        return self._service.describe().model_dump()

    async def events_after(self, seq: int) -> dict[str, Any]:
        return await self._service.events_after(seq)
