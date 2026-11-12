"""Evaluation of a trained checkpoint on the held-out split."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ultralytics import YOLO

from rdd.config import TrainConfig


@dataclass(frozen=True)
class ClassMetrics:
    precision: float
    recall: float
    ap50: float
    ap50_95: float


@dataclass(frozen=True)
class EvalMetrics:
    map50: float
    map50_95: float
    precision: float
    recall: float
    per_class: dict[str, ClassMetrics]

    def flat(self, prefix: str) -> dict[str, float]:
        """Metric name -> value, for MLflow."""
        out = {
            f"{prefix}/mAP50": self.map50,
            f"{prefix}/mAP50-95": self.map50_95,
            f"{prefix}/precision": self.precision,
            f"{prefix}/recall": self.recall,
        }
        for name, m in self.per_class.items():
            out[f"{prefix}/{name}/AP50"] = m.ap50
            out[f"{prefix}/{name}/AP50-95"] = m.ap50_95
            out[f"{prefix}/{name}/precision"] = m.precision
            out[f"{prefix}/{name}/recall"] = m.recall
        return out


def evaluate(cfg: TrainConfig, weights: Path, run_name: str) -> EvalMetrics:
    model = YOLO(str(weights))
    results = model.val(
        data=str(cfg.data.resolve()),  # absolute: dataset.yaml is located relative to it
        split=cfg.evaluate.split,
        conf=cfg.evaluate.conf,
        imgsz=cfg.train.imgsz,
        batch=cfg.train.batch,
        workers=cfg.train.workers,
        device=cfg.train.device,
        plots=cfg.train.plots,
        project=str(cfg.output_dir.resolve()),
        name=f"{run_name}-{cfg.evaluate.split}",
        exist_ok=True,
    )
    box = results.box
    # Per-class arrays only cover classes that occur in the split; ap_class_index maps
    # array position -> class index.
    per_class = {
        results.names[int(class_index)]: ClassMetrics(
            precision=float(box.p[i]),
            recall=float(box.r[i]),
            ap50=float(box.ap50[i]),
            ap50_95=float(box.ap[i]),
        )
        for i, class_index in enumerate(box.ap_class_index)
    }
    return EvalMetrics(
        map50=float(box.map50),
        map50_95=float(box.map),
        precision=float(box.mp),
        recall=float(box.mr),
        per_class=per_class,
    )
