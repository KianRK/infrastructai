from pathlib import Path
from types import SimpleNamespace

import pytest

from app.model_store import resolve_alias, resolve_model


def test_model_copied_from_the_registry_reports_its_registered_version(tmp_path: Path) -> None:
    model = tmp_path / "model.onnx"
    model.touch()
    (tmp_path / "registered_model_meta").write_text(
        "model_name: roadscan-detector\nmodel_version: 3\n"
    )

    assert resolve_model(str(model)).version == "roadscan-detector v3"


def test_plain_file_reports_its_name(tmp_path: Path) -> None:
    model = tmp_path / "experiment.onnx"
    model.touch()

    assert resolve_model(str(model)).version == "experiment"


class FakeRegistry:
    """The two MLflow client calls alias resolution uses."""

    def __init__(self, tags: dict[str, str]) -> None:
        self._tags = tags

    def get_model_version_by_alias(self, name: str, alias: str) -> SimpleNamespace:
        return SimpleNamespace(version=7)

    def get_registered_model(self, name: str) -> SimpleNamespace:
        return SimpleNamespace(tags=self._tags)


AZURE_ML = "azureml://swedencentral.api.azureml.ms/mlflow/v1.0/subscriptions/x"


def test_alias_is_resolved_natively_on_an_mlflow_server() -> None:
    registry = FakeRegistry({"alias.production": "3"})

    assert resolve_alias(registry, "roadscan-detector", "production", "http://mlflow:5000") == "7"


def test_alias_is_read_from_the_model_tag_on_azure_ml() -> None:
    registry = FakeRegistry({"alias.production": "3"})

    assert resolve_alias(registry, "roadscan-detector", "production", AZURE_ML) == "3"


def test_missing_alias_tag_on_azure_ml_is_reported() -> None:
    with pytest.raises(LookupError, match=r"no tag 'alias\.production'"):
        resolve_alias(FakeRegistry({}), "roadscan-detector", "production", AZURE_ML)
