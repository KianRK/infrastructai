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


class AppArgs(_Args):
    detector: DetectorArgs = Field(default_factory=DummyDetectorArgs)
    llm: LLMArgs = Field(default_factory=DummyLLMArgs)
    max_image_pixels: int = Field(default=40_000_000, gt=0)
