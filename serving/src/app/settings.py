"""Application arguments, supplied through the Ray Serve config file (``args:``)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DummyDetectorArgs(_Args):
    backend: Literal["dummy"] = "dummy"


class OnnxDetectorArgs(_Args):
    backend: Literal["onnx"]
    # MLflow registry URI ("models:/roadscan-detector@production") or path to an .onnx file.
    model_uri: str
    # MLflow tracking/registry server; defaults to the MLFLOW_TRACKING_URI environment variable.
    tracking_uri: str | None = None
    # Detections below this confidence are not returned. The exported model itself already
    # drops everything below its own (lower) export threshold.
    confidence_threshold: float = Field(default=0.25, gt=0, lt=1)
    threads: int | None = Field(default=None, ge=1)


DetectorArgs = Annotated[DummyDetectorArgs | OnnxDetectorArgs, Field(discriminator="backend")]


class _GenerationArgs(_Args):
    max_tokens: int = Field(default=300, ge=16)
    temperature: float = Field(default=0.2, ge=0, le=2)


class DummyLLMArgs(_Args):
    backend: Literal["dummy"] = "dummy"


class LlamaCppArgs(_GenerationArgs):
    """Quantized GGUF model on CPU (the default deployment)."""

    backend: Literal["llama_cpp"]
    repo_id: str = "Qwen/Qwen2.5-1.5B-Instruct-GGUF"
    filename: str = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
    revision: str | None = None  # Hugging Face commit, pinned in the config files
    # A local GGUF file (e.g. baked into the image) takes precedence over the download.
    model_path: Path | None = None
    context_tokens: int = Field(default=2048, ge=512)
    threads: int | None = Field(default=None, ge=1)


class VllmArgs(_GenerationArgs):
    """Full-precision model on a GPU node (optional)."""

    backend: Literal["vllm"]
    model: str = "Qwen/Qwen2.5-1.5B-Instruct"
    revision: str | None = None
    context_tokens: int = Field(default=2048, ge=512)
    gpu_memory_utilization: float = Field(default=0.85, gt=0, le=1)


LLMArgs = Annotated[DummyLLMArgs | LlamaCppArgs | VllmArgs, Field(discriminator="backend")]


class RateLimit(_Args):
    """At most ``limit`` requests per ``window_seconds`` for one key."""

    limit: int = Field(ge=1)
    window_seconds: float = Field(gt=0)


class AuthArgs(_Args):
    """Session and rate-limit settings. The secrets themselves are never in a config file:
    they are read from ``secrets_dir`` (files ``demo-password`` and ``jwt-secret``, mounted
    from Azure Key Vault) or, for local runs, from the environment variables
    ROADSCAN_DEMO_PASSWORD and ROADSCAN_JWT_SECRET."""

    secrets_dir: Path | None = None
    session_minutes: int = Field(default=60, ge=1)
    # False only for local HTTP; browsers do not send Secure cookies over plain HTTP.
    cookie_secure: bool = True
    # Number of trusted reverse proxies in front of the app that append the client address
    # to X-Forwarded-For. 0: use the TCP peer address and ignore the header.
    trusted_proxy_hops: int = Field(default=0, ge=0)
    login_limit: RateLimit = RateLimit(limit=10, window_seconds=300)  # per client address
    analyze_session_limit: RateLimit = RateLimit(limit=6, window_seconds=60)
    analyze_client_limit: RateLimit = RateLimit(limit=20, window_seconds=60)


class UploadArgs(_Args):
    max_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    # Checked from the image header before any pixel is decoded (decompression bombs).
    max_pixels: int = Field(default=50_000_000, gt=0)
    # Larger images are downscaled right after decoding; the detector works at 640 px.
    max_side: int = Field(default=1600, ge=320)


COCO_TRAFFIC_CLASSES = ("person", "bicycle", "car", "motorcycle", "bus", "truck", "train")


class _TrafficArgs(_Args):
    """Settings of the live-traffic page that do not depend on the model backend."""

    # Frames analysed per second and stream, at most. Frames that cannot be analysed in
    # time are dropped; the achieved rate is part of the statistics.
    max_fps: float = Field(default=5.0, gt=0, le=30)
    # The analysis pauses when nobody has been watching for this long.
    idle_seconds: float = Field(default=20.0, gt=0)
    # Browsers play the video this far behind the server's clock, so the result for a
    # frame has arrived before the frame is shown.
    display_delay_seconds: float = Field(default=1.5, ge=0, le=10)
    # Concurrent event-stream connections; further viewers get 503.
    max_viewers: int = Field(default=20, ge=1)
    # An event stream is closed after this long and the browser reconnects, so the
    # connection never runs into a proxy's request timeout.
    connection_seconds: float = Field(default=120.0, gt=1)
    # Tracker: overlap needed to continue a track, frames a track survives unseen, and
    # frames an object must be seen before it is shown and before it is counted. The
    # defaults were chosen by looking at the two demo videos at 5 frames per second;
    # there is no ground truth for them.
    track_iou: float = Field(default=0.2, gt=0, lt=1)
    track_max_missed: int = Field(default=15, ge=0)
    track_min_hits: int = Field(default=3, ge=1)
    track_count_hits: int = Field(default=8, ge=1)


class DummyTrafficArgs(_TrafficArgs):
    """Synthetic streams without video files or model weights."""

    backend: Literal["dummy"] = "dummy"


class OnnxTrafficArgs(_TrafficArgs):
    """Pretrained COCO detector on the prepared videos in ``media_dir``."""

    backend: Literal["onnx"]
    # MLflow registry URI ("models:/roadscan-traffic@production") or path to an .onnx file.
    model_uri: str
    tracking_uri: str | None = None
    # Directory written by serving/media/prepare.py: manifest.json, <id>.mp4 and
    # <id>.analysis.mp4 per stream.
    media_dir: Path
    confidence_threshold: float = Field(default=0.35, gt=0, lt=1)
    threads: int | None = Field(default=None, ge=1)
    # COCO class names that are reported; everything else the model finds is ignored.
    classes: tuple[str, ...] = COCO_TRAFFIC_CLASSES


TrafficArgs = Annotated[DummyTrafficArgs | OnnxTrafficArgs, Field(discriminator="backend")]


class AppArgs(_Args):
    detector: DetectorArgs = Field(default_factory=DummyDetectorArgs)
    llm: LLMArgs = Field(default_factory=DummyLLMArgs)
    traffic: TrafficArgs = Field(default_factory=DummyTrafficArgs)
    auth: AuthArgs = Field(default_factory=AuthArgs)
    upload: UploadArgs = Field(default_factory=UploadArgs)
    # How long a request waits for a model before the API answers 503. Without a limit a
    # request waits for as long as a model replica is failing to start.
    detector_timeout_seconds: float = Field(default=30.0, gt=0)
    describer_timeout_seconds: float = Field(default=120.0, gt=0)
