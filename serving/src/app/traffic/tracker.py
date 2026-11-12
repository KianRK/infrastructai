"""Multi-object tracking by box overlap, and the per-stream statistics built on it.

Deliberately simple: detections of consecutive frames are matched greedily by IoU. That
is enough to give boxes stable identities at a few frames per second and to count each
road user roughly once. It does not re-identify an object after a long occlusion, so the
counts are estimates.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field

Box = tuple[float, float, float, float]  # x_min, y_min, x_max, y_max, relative to the frame


@dataclass(frozen=True)
class Observation:
    """One detection in one frame."""

    label: str
    confidence: float
    box: Box


@dataclass
class Track:
    id: int
    box: Box
    confidence: float
    hits: int = 1
    missed: int = 0
    # Confidence mass per class: detectors flip between e.g. car and truck from frame
    # to frame, the track reports the class with the most support.
    votes: defaultdict[str, float] = field(default_factory=lambda: defaultdict(float))

    @property
    def label(self) -> str:
        return max(self.votes, key=lambda name: self.votes[name])


def iou(a: Box, b: Box) -> float:
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    intersection = width * height
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union > 0 else 0.0


class Tracker:
    def __init__(
        self,
        iou_threshold: float = 0.2,
        max_missed: int = 15,
        min_hits: int = 3,
        count_hits: int | None = None,
    ) -> None:
        self._iou_threshold = iou_threshold
        self._max_missed = max_missed
        # Seen this often, a track is shown; seen ``count_hits`` times, it is counted.
        # Counting waits longer: a wrong box for half a second is harmless, a wrong
        # count stays.
        self._min_hits = min_hits
        self._count_hits = min_hits if count_hits is None else count_hits
        self._tracks: list[Track] = []
        self._next_id = 1

    def reset(self) -> None:
        """Forget all objects (the video jumped). Identifiers are not reused."""
        self._tracks = []

    def update(self, observations: list[Observation]) -> tuple[list[Track], list[str]]:
        """Feed the detections of the next frame.

        Returns the tracks to show for this frame, and the class of every track that
        is to be counted now (each track once).
        """
        pairs = sorted(
            (
                (overlap, t, o)
                for t, track in enumerate(self._tracks)
                for o, observation in enumerate(observations)
                if (overlap := iou(track.box, observation.box)) >= self._iou_threshold
            ),
            reverse=True,
        )
        matched_tracks: set[int] = set()
        matched_observations: set[int] = set()
        confirmed: list[str] = []
        for _, t, o in pairs:
            if t in matched_tracks or o in matched_observations:
                continue
            matched_tracks.add(t)
            matched_observations.add(o)
            track, observation = self._tracks[t], observations[o]
            track.box, track.confidence = observation.box, observation.confidence
            track.votes[observation.label] += observation.confidence
            track.hits += 1
            track.missed = 0
            if track.hits == self._count_hits:
                confirmed.append(track.label)

        for t, track in enumerate(self._tracks):
            if t not in matched_tracks:
                track.missed += 1
        self._tracks = [track for track in self._tracks if track.missed <= self._max_missed]

        for o, observation in enumerate(observations):
            if o in matched_observations:
                continue
            track = Track(self._next_id, observation.box, observation.confidence)
            track.votes[observation.label] += observation.confidence
            self._next_id += 1
            self._tracks.append(track)
            if self._count_hits == 1:
                confirmed.append(track.label)

        visible = [
            track for track in self._tracks if track.missed == 0 and track.hits >= self._min_hits
        ]
        return visible, confirmed


class StreamStatistics:
    """Running numbers for one stream. Times are seconds on the caller's clock."""

    RATE_WINDOW = 60.0
    SPEED_WINDOW = 10.0

    def __init__(self) -> None:
        self.counted: Counter[str] = Counter()
        self.dropped_frames = 0
        self._counted_at: deque[float] = deque()
        self._frames: deque[tuple[float, float]] = deque()  # (time, inference seconds)

    def frame(self, now: float, inference_seconds: float, confirmed: list[str]) -> None:
        self.counted.update(confirmed)
        self._counted_at.extend(now for _ in confirmed)
        self._frames.append((now, inference_seconds))
        self._expire(now)

    def _expire(self, now: float) -> None:
        while self._counted_at and now - self._counted_at[0] > self.RATE_WINDOW:
            self._counted_at.popleft()
        while self._frames and now - self._frames[0][0] > self.SPEED_WINDOW:
            self._frames.popleft()

    @property
    def per_minute(self) -> int:
        return len(self._counted_at)

    @property
    def analysis_fps(self) -> float:
        if len(self._frames) < 2:
            return 0.0
        span = self._frames[-1][0] - self._frames[0][0]
        return (len(self._frames) - 1) / span if span > 0 else 0.0

    @property
    def inference_ms(self) -> float:
        if not self._frames:
            return 0.0
        return 1000 * sum(seconds for _, seconds in self._frames) / len(self._frames)
