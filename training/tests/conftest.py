from pathlib import Path

import pytest

from rdd.config import DataConfig


@pytest.fixture
def data_config(tmp_path: Path) -> DataConfig:
    """A small config pointing at temporary directories."""
    return DataConfig.model_validate(
        {
            "classes": {"D00": "longitudinal crack", "D10": "transverse crack"},
            "countries": ["Aland", "Borduria"],
            "download": {"url": "https://example.invalid/rdd.zip", "archive_prefix": "RDD/"},
            "prepare": {"max_image_side": 100},
            "split": {"train": 0.6, "val": 0.2, "test": 0.2, "seed": 7},
            "paths": {"raw": tmp_path / "raw", "processed": tmp_path / "processed"},
        }
    )
