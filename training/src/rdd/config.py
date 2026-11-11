"""Typed, validated configuration loaded from the YAML files in ``configs/``."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Self

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
