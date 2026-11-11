"""Train -> evaluate -> export -> quality gate -> register, tracked as one MLflow run.

Usage::

    python -m rdd.pipeline [--config configs/train.yaml]
    python -m rdd.pipeline --weights runs/<name>/weights/best.pt   # skip training

The second form re-evaluates and registers an existing checkpoint, e.g. against the
Azure ML workspace (set MLFLOW_TRACKING_URI) after training against a local server.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import mlflow

from rdd.config import TrainConfig
from rdd.evaluate import EvalMetrics, evaluate
from rdd.export import export_onnx
from rdd.registry import GateDecision, check_gate, register
from rdd.train import train

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineResult:
    run_id: str
    metrics: EvalMetrics
    gate: GateDecision
    onnx_path: Path
    model_version: str | None  # None when the gate failed


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, child in value.items():
            out.update(_flatten(child, f"{prefix}{key}."))
        return out
    return {prefix.rstrip("."): value}


def run_pipeline(cfg: TrainConfig, weights: Path | None = None) -> PipelineResult:
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI") or cfg.mlflow.tracking_uri)
    mlflow.set_experiment(cfg.mlflow.experiment)
    run_name = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")

    with mlflow.start_run(run_name=run_name) as run:
        mlflow.log_params(_flatten(cfg.model_dump(mode="json")))
        stats_path = cfg.data.parent / "stats.json"
        if stats_path.exists():
            mlflow.log_artifact(str(stats_path), "data")

        if weights is None:
            weights = train(cfg, run_name)
        else:
            mlflow.set_tag("training", f"skipped, weights from {weights}")

        metrics = evaluate(cfg, weights, run_name)
        split = cfg.evaluate.split
        mlflow.log_metrics(metrics.flat(split))
        mlflow.log_dict(asdict(metrics), f"metrics_{split}.json")
        log.info("%s metrics: %s", split, json.dumps(asdict(metrics), indent=2))

        onnx_path = export_onnx(cfg, weights)
        mlflow.log_artifact(str(weights), "checkpoint")

        gate = check_gate(metrics, cfg.gate)
        mlflow.set_tag("quality_gate", "passed" if gate.passed else "failed")
        log.info("%s", gate)
        version = register(cfg, onnx_path) if gate.passed else None
        if version is None:
            log.warning("model was NOT registered")

        return PipelineResult(run.info.run_id, metrics, gate, onnx_path, version)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=Path("configs/train.yaml"))
    parser.add_argument("--weights", type=Path, default=None, help="skip training, use these")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = run_pipeline(TrainConfig.from_yaml(args.config), args.weights)
    # A failed gate is a normal outcome, but automation should be able to detect it.
    raise SystemExit(0 if result.gate.passed else 2)


if __name__ == "__main__":
    main()
