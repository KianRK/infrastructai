"""ONNX export of a trained checkpoint for CPU serving with ONNX Runtime."""

from __future__ import annotations

from pathlib import Path

from ultralytics import YOLO

from rdd.config import TrainConfig


def export_onnx(cfg: TrainConfig, weights: Path) -> Path:
    """Export next to the checkpoint, with NMS embedded in the graph.

    Output: ``(1, max_det, 6)`` rows of ``x1, y1, x2, y2, confidence, class`` in input-pixel
    coordinates, zero-padded. Class names and image size are stored in the ONNX metadata,
    so the serving code needs neither Ultralytics nor a separate label file.
    """
    model = YOLO(str(weights))
    exported = model.export(
        format="onnx",
        imgsz=cfg.train.imgsz,
        dynamic=cfg.export.dynamic,
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
