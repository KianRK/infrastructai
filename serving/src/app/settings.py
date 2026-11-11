"""Application arguments, supplied through the Ray Serve config file (``args:``)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DetectorArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: Literal["dummy"] = "dummy"


class LLMArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: Literal["dummy"] = "dummy"


class AppArgs(BaseModel):
    """Validated by Ray Serve before the application is built."""

    model_config = ConfigDict(extra="forbid")

    detector: DetectorArgs = Field(default_factory=DetectorArgs)
    llm: LLMArgs = Field(default_factory=LLMArgs)
    max_image_pixels: int = Field(default=40_000_000, gt=0)
