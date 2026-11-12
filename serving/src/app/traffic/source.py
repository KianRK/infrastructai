"""Where the frames of a stream come from: a prepared video file, or nothing at all."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True)
class Frame:
    t: float  # position in the video, seconds
    image: NDArray[np.uint8]  # H x W x 3, RGB


class FrameSource(Protocol):
    duration: float

    def seek(self, t: float) -> None:
        """Continue with the first frame at or after ``t``."""

    def read(self) -> Frame | None:
        """The next frame, or None at the end of the video."""


class StreamMeta(BaseModel):
    """One entry of ``manifest.json``, written by serving/media/prepare.py."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9-]+$")
    title: str
    location: str
    attribution: str
    licence: str
    source_url: str
    duration: float = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


def load_manifest(media_dir: Path) -> list[StreamMeta]:
    manifest = media_dir / "manifest.json"
    if not manifest.is_file():
        raise FileNotFoundError(
            f"{manifest} not found; prepare the videos with serving/media/prepare.py"
        )
    streams = [StreamMeta.model_validate(entry) for entry in json.loads(manifest.read_text())]
    if not streams:
        raise ValueError(f"{manifest} lists no streams")
    return streams


def display_path(media_dir: Path, stream_id: str) -> Path:
    """The video the browser plays."""
    return media_dir / f"{stream_id}.mp4"


def analysis_path(media_dir: Path, stream_id: str) -> Path:
    """The same video at the model's resolution and a few frames per second, so the
    server decodes only what it analyses."""
    return media_dir / f"{stream_id}.analysis.mp4"


class VideoFileSource:
    def __init__(self, path: Path) -> None:
        import av  # not needed for the dummy backend

        self._container = av.open(str(path))
        self._stream = self._container.streams.video[0]
        if self._stream.time_base is None or self._container.duration is None:
            raise ValueError(f"{path} has no usable timing information")
        self._time_base = float(self._stream.time_base)
        self.duration = self._container.duration / av.time_base
        self._frames = self._container.decode(self._stream)
        self._skip_before = 0.0

    def seek(self, t: float) -> None:
        # Jumps to the key frame at or before t; read() skips forward from there.
        self._container.seek(int(t / self._time_base), stream=self._stream)
        self._frames = self._container.decode(self._stream)
        self._skip_before = t

    def read(self) -> Frame | None:
        for frame in self._frames:
            if frame.pts is None:
                continue
            t = frame.pts * self._time_base
            if t + 1e-6 < self._skip_before:
                continue
            self._skip_before = 0.0
            return Frame(t, np.asarray(frame.to_ndarray(format="rgb24"), dtype=np.uint8))
        return None


class SyntheticSource:
    """Frames without content, for the dummy backend: only their timestamps matter."""

    _IMAGE = np.zeros((36, 64, 3), dtype=np.uint8)

    def __init__(self, duration: float, fps: float) -> None:
        self.duration = duration
        self._step = 1.0 / fps
        self._index = 0

    def seek(self, t: float) -> None:
        self._index = max(0, int(np.ceil(t / self._step - 1e-9)))

    def read(self) -> Frame | None:
        t = self._index * self._step
        if t >= self.duration - 1e-9:
            return None
        self._index += 1
        return Frame(t, self._IMAGE)
