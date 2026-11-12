"""Detector training with Ultralytics, reporting per-epoch metrics to the active MLflow run."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import mlflow
from ultralytics import YOLO
from ultralytics.utils import SETTINGS

from rdd.config import TrainConfig

log = logging.getLogger(__name__)

_INTEGRATIONS = ("clearml", "comet", "dvc", "mlflow", "raytune", "tensorboard", "wandb")


def disable_builtin_loggers() -> None:
    """Turn off Ultralytics' own experiment loggers for this process.

    Whether they run depends on a per-user settings file, which would make tracking
    differ between machines. This pipeline logs to MLflow itself instead. ``dict.update``
    is used on purpose: the regular setter would write the change to the user's file.
    """
    dict.update(SETTINGS, dict.fromkeys(_INTEGRATIONS, False))


def metric_name(key: str) -> str:
    """Ultralytics metric key -> MLflow-safe name, e.g. 'metrics/mAP50(B)' -> 'metrics/mAP50'."""
    return key.replace("(B)", "").replace("(", "_").replace(")", "")


def _log_epoch(trainer: Any) -> None:
    metrics = {**trainer.label_loss_items(trainer.tloss, prefix="train"), **trainer.metrics}
    mlflow.log_metrics(
        {metric_name(k): float(v) for k, v in metrics.items()}, step=int(trainer.epoch)
    )


def train(cfg: TrainConfig, run_name: str) -> Path:
    """Train and return the path of the best checkpoint (selected on the val split)."""
    disable_builtin_loggers()
    model = YOLO(cfg.model.weights)
    model.add_callback("on_fit_epoch_end", _log_epoch)
    params = cfg.train
    model.train(
        data=str(cfg.data.resolve()),  # absolute: dataset.yaml is located relative to it
        epochs=params.epochs,
        imgsz=params.imgsz,
        batch=params.batch,
        amp=params.amp,
        workers=params.workers,
        patience=params.patience,
        seed=params.seed,
        device=params.device,
        plots=params.plots,
        project=str(cfg.output_dir.resolve()),
        name=run_name,
        exist_ok=True,
        **params.extra,
    )
    best = Path(model.trainer.best)
    if not best.exists():
        raise RuntimeError(f"training finished without a checkpoint at {best}")
    return best
