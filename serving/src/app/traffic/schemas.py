"""Public contract of the live-traffic endpoints. The frontend's types mirror these."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TrackedObject(_Schema):
    # Stable while the object stays in view, so the frontend can animate its box.
    id: int
    label: str = Field(description="COCO class name, e.g. 'car'.")
    confidence: float = Field(ge=0, le=1)
    # x_min, y_min, x_max, y_max relative to the frame size (0..1).
    box: tuple[float, float, float, float]


class StreamStats(_Schema):
    in_view: dict[str, int] = Field(description="Objects in the current frame, per class.")
    counted: dict[str, int] = Field(
        description="Distinct tracked objects since the analysis started, per class."
    )
    per_minute: int = Field(description="Objects newly counted in the last 60 seconds.")
    analysis_fps: float = Field(description="Frames analysed per second, last 10 seconds.")
    inference_ms: float = Field(description="Mean model time per frame, last 10 seconds.")
    dropped_frames: int = Field(description="Frames skipped because the analysis was behind.")


class StreamEvent(_Schema):
    """The analysis result of one video frame."""

    stream: str
    seq: int = Field(description="Increases by one per event across all streams.")
    t: float = Field(description="Position of the frame in the video, in seconds.")
    objects: list[TrackedObject]
    stats: StreamStats


class StreamInfo(_Schema):
    id: str
    title: str
    location: str
    # Shown next to the video: the clips are used under Creative Commons licences.
    attribution: str
    licence: str
    source_url: str
    duration: float = Field(gt=0, description="Length of the loop in seconds.")
    position: float = Field(ge=0, description="Where the server's clock is in the loop.")
    video_url: str | None = Field(description="None for synthetic streams (dummy backend).")
    aspect_ratio: float = Field(gt=0, description="Width divided by height.")


class StreamList(_Schema):
    streams: list[StreamInfo]
    classes: list[str]
    delay_seconds: float = Field(description="How far behind `position` the video is shown.")
    detector_version: str
