"""Quality gate and MLflow model registry operations."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

import mlflow
import onnx
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

from rdd.config import GateConfig, TrainConfig
from rdd.evaluate import EvalMetrics

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GateDecision:
    passed: bool
    metric: str
    value: float
    threshold: float

    def __str__(self) -> str:
        verdict = "passed" if self.passed else "failed"
        return f"quality gate {verdict}: {self.metric}={self.value:.4f}, need >= {self.threshold}"


def check_gate(metrics: EvalMetrics, cfg: GateConfig) -> GateDecision:
    value = {"map50": metrics.map50, "map50_95": metrics.map50_95}[cfg.metric]
    return GateDecision(value >= cfg.threshold, cfg.metric, value, cfg.threshold)


def alias_tag(alias: str) -> str:
    """Registered-model tag that stands in for an alias where aliases do not exist."""
    return f"alias.{alias}"


def has_native_registry(tracking_uri: str) -> bool:
    """Azure ML implements neither MLflow's model aliases nor the logged-model API that
    ``log_model`` uses since MLflow 3 (both answer 404; checked 2026-11)."""
    return not tracking_uri.startswith("azureml://")


def _register_from_artifacts(client: MlflowClient, model: onnx.ModelProto, name: str) -> str:
    """Registry path that only needs run artifacts and plain model versions."""
    run = mlflow.active_run()
    if run is None:
        raise RuntimeError("register() needs an active MLflow run")
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "detector"
        mlflow.onnx.save_model(model, str(local))
        mlflow.log_artifacts(str(local), "detector")
    try:
        client.create_registered_model(name)
    except MlflowException as exc:
        if exc.error_code != "RESOURCE_ALREADY_EXISTS":
            raise
    source = mlflow.get_artifact_uri("detector")
    return str(client.create_model_version(name, source=source, run_id=run.info.run_id).version)


def register(cfg: TrainConfig, onnx_path: Path) -> str:
    """Log the ONNX model to the active run, register it, and point the alias at it.

    Returns the new model version. On Azure ML the alias is recorded as the
    registered-model tag ``alias.<alias>`` holding the version; the serving application
    resolves it the same way.
    """
    name, alias = cfg.mlflow.registered_model, cfg.gate.alias
    model = onnx.load(str(onnx_path))
    client = MlflowClient()
    if has_native_registry(mlflow.get_tracking_uri()):
        info = mlflow.onnx.log_model(model, name="detector", registered_model_name=name)
        version = str(info.registered_model_version)
        client.set_registered_model_alias(name, alias, version)
    else:
        version = _register_from_artifacts(client, model, name)
        client.set_registered_model_tag(name, alias_tag(alias), version)
    log.info("registered %s v%s as @%s", name, version, alias)
    return version
