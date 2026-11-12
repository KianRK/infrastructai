"""Locates the detector model: MLflow model registry or a local file."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REGISTRY_URI = re.compile(r"^models:/(?P<name>[^/@]+)(?:@(?P<alias>[^/@]+)|/(?P<version>\d+))$")


@dataclass(frozen=True)
class ResolvedModel:
    path: Path
    version: str  # shown in API responses, e.g. "roadscan-detector v3"


@dataclass(frozen=True)
class RegistryRef:
    name: str
    alias: str | None
    version: str | None


def parse_registry_uri(uri: str) -> RegistryRef:
    match = _REGISTRY_URI.match(uri)
    if match is None:
        raise ValueError(
            f"unsupported model URI {uri!r}; expected models:/<name>@<alias> or models:/<name>/<n>"
        )
    return RegistryRef(match["name"], match["alias"], match["version"])


def _downloaded_version(path: Path) -> str | None:
    """Name and version of a model copied out of the registry (`make model-fetch`).

    MLflow writes them to a ``registered_model_meta`` file next to the model.
    """
    meta = path.with_name("registered_model_meta")
    if not meta.is_file():
        return None
    lines = (line.partition(":") for line in meta.read_text().splitlines())
    fields = {key.strip(): value.strip() for key, _, value in lines}
    name, version = fields.get("model_name"), fields.get("model_version")
    return f"{name} v{version}" if name and version else None


def resolve_alias(client: Any, name: str, alias: str, tracking_uri: str) -> str:
    """Version an alias points to.

    Azure ML has no model aliases (its MLflow endpoint answers 404). There the training
    pipeline records the alias as the registered-model tag ``alias.<alias>`` holding the
    version number.
    """
    if not tracking_uri.startswith("azureml://"):
        return str(client.get_model_version_by_alias(name, alias).version)
    version = client.get_registered_model(name).tags.get(f"alias.{alias}")
    if not version:
        raise LookupError(f"registered model {name!r} has no tag 'alias.{alias}'")
    return str(version)


def resolve_model(model_uri: str, tracking_uri: str | None = None) -> ResolvedModel:
    if not model_uri.startswith("models:/"):
        path = Path(model_uri)
        if not path.is_file():
            raise FileNotFoundError(f"detector model not found: {path}")
        return ResolvedModel(path, _downloaded_version(path) or path.stem)

    # Imported here so local-file and dummy setups do not pay MLflow's import time.
    import mlflow
    from mlflow import MlflowClient

    ref = parse_registry_uri(model_uri)
    tracking_uri = tracking_uri or os.environ.get("MLFLOW_TRACKING_URI")
    if not tracking_uri:
        raise ValueError("a registry model needs tracking_uri or MLFLOW_TRACKING_URI")
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_registry_uri(tracking_uri)

    version = ref.version
    if ref.alias is not None:
        version = resolve_alias(MlflowClient(), ref.name, ref.alias, tracking_uri)
    # Download the resolved version, so the reported version is the one that is served
    # even if the alias moves while this replica starts.
    local_dir = Path(mlflow.artifacts.download_artifacts(f"models:/{ref.name}/{version}"))
    candidates = sorted(local_dir.rglob("*.onnx"))
    if len(candidates) != 1:
        raise RuntimeError(f"expected one .onnx file in {model_uri}, found {len(candidates)}")
    return ResolvedModel(candidates[0], f"{ref.name} v{version}")
