from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from rdd.config import DataConfig

CONFIG_PATH = Path(__file__).parents[1] / "configs" / "data.yaml"


def _raw() -> dict[str, object]:
    with CONFIG_PATH.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    assert isinstance(raw, dict)
    return raw


def test_shipped_config_is_valid_and_keeps_class_order() -> None:
    cfg = DataConfig.from_yaml(CONFIG_PATH)
    # Class index order is part of the model contract: serving maps indices back to codes.
    assert cfg.class_ids == ["D00", "D10", "D20", "D40"]


def test_unknown_key_is_rejected() -> None:
    raw = _raw()
    raw["countires"] = ["Japan"]  # typo on purpose
    with pytest.raises(ValidationError, match="countires"):
        DataConfig.model_validate(raw)


def test_split_fractions_must_sum_to_one() -> None:
    raw = _raw()
    raw["split"] = {"train": 0.8, "val": 0.1, "test": 0.2, "seed": 1}
    with pytest.raises(ValidationError, match=r"sum to 1\.0"):
        DataConfig.model_validate(raw)
