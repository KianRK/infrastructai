"""Export a published checkpoint to ONNX and register it, tracked as one MLflow run.

Usage::

    python -m rdd.pretrained [--config configs/traffic.yaml]

Used for the detector of the live-traffic page, which needs the COCO classes and no
training of its own. It goes through the same registry as the trained detector, so the
serving stack loads both the same way.
"""

from __future__ import annotations

import argparse
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import mlflow
from ultralytics import YOLO

from rdd.config import PretrainedConfig
from rdd.registry import register_onnx

log = logging.getLogger(__name__)


def export_pretrained(cfg: PretrainedConfig) -> Path:
    """Download the checkpoint into ``output_dir`` and export it next to it."""
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    model = YOLO(str(cfg.output_dir / cfg.model.weights))
    exported = model.export(
        format="onnx",
        imgsz=list(cfg.export.imgsz),
        simplify=cfg.export.simplify,
        nms=True,
        conf=cfg.export.conf,
        iou=cfg.export.iou,
        max_det=cfg.export.max_det,
        device="cpu",
    )
    path = Path(exported)
    if not path.exists():
        raise RuntimeError(f"export did not produce {path}")
    return path


def run(cfg: PretrainedConfig) -> str:
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI") or cfg.mlflow.tracking_uri)
    mlflow.set_experiment(cfg.mlflow.experiment)
    with mlflow.start_run(run_name=datetime.now(UTC).strftime("%Y%m%d-%H%M%S")):
        mlflow.log_params(
            {"weights": cfg.model.weights, **{f"export.{k}": v for k, v in cfg.export}}
        )
        mlflow.set_tag("training", "none, published checkpoint")
        return register_onnx(export_pretrained(cfg), cfg.mlflow.registered_model, cfg.alias)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=Path("configs/traffic.yaml"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    version = run(PretrainedConfig.from_yaml(args.config))
    log.info("registered version %s", version)


if __name__ == "__main__":
    main()
