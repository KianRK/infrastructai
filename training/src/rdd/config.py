"""Typed, validated configuration loaded from the YAML files in ``configs/``."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class _StrictModel(BaseModel):
    # Reject unknown keys so a typo in a config file fails loudly instead of
    # silently falling back to a default.
    model_config = ConfigDict(extra="forbid", frozen=True)


class SplitConfig(_StrictModel):
    train: float = Field(gt=0, lt=1)
    val: float = Field(gt=0, lt=1)
    test: float = Field(ge=0, lt=1)
    seed: int

    @model_validator(mode="after")
    def _fractions_sum_to_one(self) -> Self:
        total = self.train + self.val + self.test
        if not math.isclose(total, 1.0, abs_tol=1e-6):
            raise ValueError(f"split fractions must sum to 1.0, got {total}")
        return self


class DownloadConfig(_StrictModel):
    url: HttpUrl
    archive_prefix: str
    keep_archives: bool = False


class PrepareConfig(_StrictModel):
    max_image_side: int | None = Field(default=None, ge=64)
    jpeg_quality: int = Field(default=90, ge=1, le=95)


class PathsConfig(_StrictModel):
    raw: Path
    processed: Path


class DataConfig(_StrictModel):
    classes: dict[str, str] = Field(min_length=1)
    countries: list[str] = Field(min_length=1)
    download: DownloadConfig
    prepare: PrepareConfig
    split: SplitConfig
    paths: PathsConfig

    @property
    def class_ids(self) -> list[str]:
        """Class codes in class-index order (the order they appear in the config)."""
        return list(self.classes)

    @classmethod
    def from_yaml(cls, path: Path) -> Self:
        with path.open(encoding="utf-8") as fh:
            return cls.model_validate(yaml.safe_load(fh))


class ModelConfig(_StrictModel):
    weights: str


class TrainParams(_StrictModel):
    epochs: int = Field(ge=1)
    imgsz: int = Field(ge=32, multiple_of=32)
    batch: int = Field(ge=1)
    amp: bool = True
    workers: int = Field(default=8, ge=0)
    patience: int = Field(default=20, ge=0)
    seed: int = 42
    device: str = "0"
    plots: bool = True
    extra: dict[str, Any] = Field(default_factory=dict)


class EvaluateConfig(_StrictModel):
    split: Literal["val", "test"] = "test"
    conf: float = Field(default=0.001, gt=0, lt=1)


class ExportConfig(_StrictModel):
    dynamic: bool = False
    simplify: bool = True
    conf: float = Field(default=0.10, gt=0, lt=1)
    iou: float = Field(default=0.5, gt=0, lt=1)
    max_det: int = Field(default=100, ge=1)


class MlflowConfig(_StrictModel):
    tracking_uri: str
    experiment: str
    registered_model: str


class GateConfig(_StrictModel):
    metric: Literal["map50", "map50_95"]
    threshold: float = Field(ge=0, le=1)
    alias: str = Field(min_length=1)


class TrainConfig(_StrictModel):
    data: Path
    output_dir: Path
    model: ModelConfig
    train: TrainParams
    evaluate: EvaluateConfig
    export: ExportConfig
    mlflow: MlflowConfig
    gate: GateConfig

    @classmethod
    def from_yaml(cls, path: Path) -> Self:
        with path.open(encoding="utf-8") as fh:
            return cls.model_validate(yaml.safe_load(fh))
