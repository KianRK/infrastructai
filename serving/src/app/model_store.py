"""Locates the detector model: MLflow model registry or a local file."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

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


def resolve_model(model_uri: str, tracking_uri: str | None = None) -> ResolvedModel:
    if not model_uri.startswith("models:/"):
        path = Path(model_uri)
        if not path.is_file():
            raise FileNotFoundError(f"detector model not found: {path}")
        return ResolvedModel(path, path.stem)

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
        client = MlflowClient()
        version = str(client.get_model_version_by_alias(ref.name, ref.alias).version)
    # Download the resolved version, so the reported version is the one that is served
    # even if the alias moves while this replica starts.
    local_dir = Path(mlflow.artifacts.download_artifacts(f"models:/{ref.name}/{version}"))
    candidates = sorted(local_dir.rglob("*.onnx"))
    if len(candidates) != 1:
        raise RuntimeError(f"expected one .onnx file in {model_uri}, found {len(candidates)}")
    return ResolvedModel(candidates[0], f"{ref.name} v{version}")
