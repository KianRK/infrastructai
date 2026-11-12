"""Detector pre- and postprocessing: letterboxing and mapping boxes back to the image.

Pure NumPy/Pillow code that mirrors what Ultralytics does at training/validation time,
so the ONNX model sees the same kind of input in production.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from app.schemas import DAMAGE_CLASS_NAMES, BoundingBox, DamageClass, Detection

PAD_VALUE = 114  # grey border used by Ultralytics


@dataclass(frozen=True)
class Letterbox:
    """How an image was placed on the square model input."""

    scale: float  # model-input pixels per original pixel
    pad_x: int  # left border in model-input pixels
    pad_y: int  # top border
    width: int  # original image size
    height: int


def letterbox(image: NDArray[np.uint8], size: int) -> tuple[NDArray[np.float32], Letterbox]:
    """Resize keeping the aspect ratio, pad to ``size`` x ``size``, scale to 0..1, NCHW."""
    height, width = image.shape[:2]
    scale = min(size / width, size / height)
    new_w, new_h = max(1, round(width * scale)), max(1, round(height * scale))
    pad_x, pad_y = (size - new_w) // 2, (size - new_h) // 2

    resized = Image.fromarray(image).resize((new_w, new_h), Image.Resampling.BILINEAR)
    canvas = np.full((size, size, 3), PAD_VALUE, dtype=np.uint8)
    canvas[pad_y : pad_y + new_h, pad_x : pad_x + new_w] = np.asarray(resized)

    tensor = canvas.astype(np.float32).transpose(2, 0, 1)[np.newaxis] / 255.0
    return np.ascontiguousarray(tensor), Letterbox(scale, pad_x, pad_y, width, height)


def _relative(value: float, extent: float) -> float:
    """Position as a fraction of the image extent, clipped to the image. Rounded because
    more digits than this are float32 noise that only bloats the JSON response."""
    return round(min(max(value / extent, 0.0), 1.0), 5)


def to_detections(
    rows: NDArray[np.float32],
    box: Letterbox,
    class_names: Mapping[int, str],
    confidence_threshold: float,
) -> list[Detection]:
    """Convert model output rows to API detections, most confident first.

    ``rows`` has shape (N, 6): x1, y1, x2, y2 in model-input pixels, confidence, class
    index. NMS is part of the exported model; unused rows are all zeros.
    """
    detections = []
    for x1, y1, x2, y2, confidence, class_index in rows.tolist():
        if confidence < confidence_threshold:
            continue  # also skips the zero padding
        try:
            damage_class = DamageClass(class_names[int(class_index)])
        except (KeyError, ValueError):
            continue  # a class this API does not know about
        # Undo the letterbox, then express relative to the original image and clip.
        x_min = _relative(x1 - box.pad_x, box.scale * box.width)
        x_max = _relative(x2 - box.pad_x, box.scale * box.width)
        y_min = _relative(y1 - box.pad_y, box.scale * box.height)
        y_max = _relative(y2 - box.pad_y, box.scale * box.height)
        if x_max <= x_min or y_max <= y_min:
            continue  # lay entirely in the padding
        detections.append(
            Detection(
                damage_class=damage_class,
                label=DAMAGE_CLASS_NAMES[damage_class],
                confidence=round(min(max(confidence, 0.0), 1.0), 4),
                box=BoundingBox(x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max),
            )
        )
    return sorted(detections, key=lambda d: d.confidence, reverse=True)
