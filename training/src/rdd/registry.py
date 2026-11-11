"""Quality gate and MLflow model registry operations."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import mlflow
import onnx
from mlflow import MlflowClient

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


def register(cfg: TrainConfig, onnx_path: Path) -> str:
    """Log the ONNX model to the active run, register it, and point the alias at it.

    Returns the new model version.
    """
    info = mlflow.onnx.log_model(
        onnx.load(str(onnx_path)),
        name="detector",
        registered_model_name=cfg.mlflow.registered_model,
    )
    version = str(info.registered_model_version)
    MlflowClient().set_registered_model_alias(cfg.mlflow.registered_model, cfg.gate.alias, version)
    log.info("registered %s v%s as @%s", cfg.mlflow.registered_model, version, cfg.gate.alias)
    return version
