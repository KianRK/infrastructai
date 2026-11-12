"""The analysis itself: each stream is played against the wall clock, like a camera feed.

A stream's position is defined by the clock alone (``(now - epoch) % duration``), so the
server and every browser agree on what is "live" without exchanging frames. The server
analyses the frames as their time comes and drops those it is too late for.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import Counter, deque
from collections.abc import Callable
from typing import Any

from app.settings import DummyTrafficArgs, OnnxTrafficArgs, TrafficArgs
from app.traffic.detector import DummyTrafficBackend, OnnxTrafficBackend, TrafficBackend
from app.traffic.schemas import StreamEvent, StreamInfo, StreamList, StreamStats, TrackedObject
from app.traffic.source import (
    Frame,
    FrameSource,
    StreamMeta,
    SyntheticSource,
    VideoFileSource,
    analysis_path,
    load_manifest,
)
from app.traffic.tracker import StreamStatistics, Tracker

log = logging.getLogger("ray.serve")

# A frame that is this late is skipped instead of analysed.
MAX_LAG_SECONDS = 0.75


class StreamWorker:
    """One stream: source, detector, tracker and statistics. Not thread-safe; one caller."""

    def __init__(
        self,
        meta: StreamMeta,
        source: FrameSource,
        backend: TrafficBackend,
        args: TrafficArgs,
        epoch: float,
    ) -> None:
        self.meta = meta
        self._source = source
        self._backend = backend
        self._tracker = Tracker(
            args.track_iou, args.track_max_missed, args.track_min_hits, args.track_count_hits
        )
        self._stats = StreamStatistics()
        self._epoch = epoch
        # The loop length is that of the video the browser plays; the analysis copy may
        # differ from it by a fraction of a frame.
        self._duration = meta.duration
        self._min_interval = 1.0 / args.max_fps
        self._loop = 0
        self._pending: Frame | None = None
        self._last_analysed = float("-inf")  # stream time, increasing across loops

    def position(self, now: float) -> float:
        return (now - self._epoch) % self._duration

    def resync(self, now: float) -> None:
        """Jump to the current position, e.g. after the analysis was paused."""
        elapsed = max(0.0, now - self._epoch)
        self._loop = int(elapsed // self._duration)
        self._source.seek(elapsed % self._duration)
        self._pending = None
        self._last_analysed = float("-inf")
        self._tracker.reset()

    def _read(self) -> Frame:
        frame = self._source.read()
        if frame is None or frame.t >= self._duration:  # end of the video: start over
            self._loop += 1
            self._source.seek(0.0)
            self._tracker.reset()
            frame = self._source.read()
            if frame is None:
                raise RuntimeError(f"stream {self.meta.id!r} has no frames")
        return frame

    def advance(self, now: float) -> tuple[StreamEvent | None, float]:
        """Handle at most one frame.

        Returns the analysis of a frame whose time has come (None if there is none or
        it was skipped) and how long to wait before the next call.
        """
        if self._pending is None:
            self._pending = self._read()
        frame = self._pending
        stream_time = self._loop * self._duration + frame.t
        due = self._epoch + stream_time
        if due > now:
            return None, due - now
        self._pending = None
        if stream_time - self._last_analysed < self._min_interval - 1e-6:
            return None, 0.0  # more frames in the file than max_fps asks for
        if now - due > MAX_LAG_SECONDS:
            self._stats.dropped_frames += 1
            return None, 0.0
        self._last_analysed = stream_time

        started = time.perf_counter()
        observations = self._backend.detect(frame)
        elapsed = time.perf_counter() - started
        visible, confirmed = self._tracker.update(observations)
        self._stats.frame(now, elapsed, confirmed)
        event = StreamEvent(
            stream=self.meta.id,
            seq=0,  # assigned when the event is published
            t=round(frame.t, 3),
            objects=[
                TrackedObject(id=t.id, label=t.label, confidence=t.confidence, box=t.box)
                for t in visible
            ],
            stats=StreamStats(
                in_view=dict(Counter(t.label for t in visible)),
                counted=dict(self._stats.counted),
                per_minute=self._stats.per_minute,
                analysis_fps=round(self._stats.analysis_fps, 1),
                inference_ms=round(self._stats.inference_ms, 1),
                dropped_frames=self._stats.dropped_frames,
            ),
        )
        return event, 0.0


SYNTHETIC_STREAMS = [
    StreamMeta(
        id=f"synthetic-{n}",
        title=f"Synthetic stream {n}",
        location="No video: dummy models",
        attribution="generated",
        licence="",
        source_url="",
        duration=60.0 + 15 * n,
        width=1280,
        height=720,
    )
    for n in (1, 2)
]


def build_workers(args: TrafficArgs, epoch: float) -> tuple[list[StreamWorker], TrafficBackend]:
    match args:
        case DummyTrafficArgs():
            dummy = DummyTrafficBackend()
            return [
                StreamWorker(m, SyntheticSource(m.duration, args.max_fps), dummy, args, epoch)
                for m in SYNTHETIC_STREAMS
            ], dummy
        case OnnxTrafficArgs():
            onnx = OnnxTrafficBackend(args)
            return [
                StreamWorker(
                    m, VideoFileSource(analysis_path(args.media_dir, m.id)), onnx, args, epoch
                )
                for m in load_manifest(args.media_dir)
            ], onnx


class TrafficService:
    """Runs the workers while somebody is watching and keeps the latest events."""

    BUFFER = 256  # events kept for subscribers that are briefly behind

    def __init__(
        self,
        args: TrafficArgs,
        workers: list[StreamWorker],
        backend: TrafficBackend,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._args = args
        self._workers = workers
        self._backend = backend
        self._clock = clock
        self._events: deque[dict[str, Any]] = deque(maxlen=self.BUFFER)
        self._seq = 0
        self._changed = asyncio.Condition()
        self._last_request = float("-inf")
        self._tasks: list[asyncio.Task[None]] = []

    def describe(self) -> StreamList:
        now = self._clock()
        has_video = isinstance(self._args, OnnxTrafficArgs)
        return StreamList(
            streams=[
                StreamInfo(
                    id=w.meta.id,
                    title=w.meta.title,
                    location=w.meta.location,
                    attribution=w.meta.attribution,
                    licence=w.meta.licence,
                    source_url=w.meta.source_url,
                    duration=w.meta.duration,
                    position=round(w.position(now), 3),
                    video_url=f"/api/traffic/streams/{w.meta.id}/video" if has_video else None,
                    aspect_ratio=round(w.meta.width / w.meta.height, 4),
                )
                for w in self._workers
            ],
            classes=list(self._args.classes) if isinstance(self._args, OnnxTrafficArgs) else [],
            delay_seconds=self._args.display_delay_seconds,
            detector_version=self._backend.version,
        )

    async def events_after(self, seq: int, wait_seconds: float = 5.0) -> dict[str, Any]:
        """Events newer than ``seq``, waiting up to ``wait_seconds`` for the first one.

        Calling this is what keeps the analysis running. ``latest`` lets a caller notice
        that this service was restarted (its sequence then starts again from zero).
        """
        self._last_request = self._clock()
        self._ensure_running()
        async with self._changed:
            if self._seq <= seq:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._changed.wait(), wait_seconds)
        return {"latest": self._seq, "events": [e for e in self._events if e["seq"] > seq]}

    @property
    def running(self) -> bool:
        return any(not task.done() for task in self._tasks)

    def _ensure_running(self) -> None:
        if self.running:
            return
        log.info("traffic analysis starts (a viewer connected)")
        self._tasks = [asyncio.create_task(self._run(worker)) for worker in self._workers]

    async def _run(self, worker: StreamWorker) -> None:
        try:
            await asyncio.to_thread(worker.resync, self._clock())
            while self._clock() - self._last_request < self._args.idle_seconds:
                # Decoding and inference block, so they run in a worker thread and the
                # event loop keeps answering.
                event, wait = await asyncio.to_thread(worker.advance, self._clock())
                if event is not None:
                    await self._publish(event)
                if wait > 0:
                    await asyncio.sleep(min(wait, 0.5))
            log.info("traffic analysis of %s pauses (no viewers)", worker.meta.id)
        except Exception:
            log.exception("traffic analysis of %s failed", worker.meta.id)

    async def _publish(self, event: StreamEvent) -> None:
        async with self._changed:
            self._seq += 1
            self._events.append(event.model_copy(update={"seq": self._seq}).model_dump())
            self._changed.notify_all()

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
