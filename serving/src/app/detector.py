"""Detection deployment. The backend (dummy, later ONNX Runtime) is chosen by config."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray
from ray import serve

from app.schemas import DAMAGE_CLASS_NAMES, BoundingBox, DamageClass, Detection
from app.settings import DetectorArgs

Image = NDArray[np.uint8]  # H x W x 3, RGB


@dataclass(frozen=True)
class DetectorOutput:
    detections: list[Detection]
    version: str


class DetectorBackend(Protocol):
    version: str

    def detect(self, image: Image) -> list[Detection]: ...


def make_detection(
    damage_class: DamageClass, confidence: float, box: tuple[float, float, float, float]
) -> Detection:
    return Detection(
        damage_class=damage_class,
        label=DAMAGE_CLASS_NAMES[damage_class],
        confidence=confidence,
        box=BoundingBox(x_min=box[0], y_min=box[1], x_max=box[2], y_max=box[3]),
    )


class DummyDetectorBackend:
    """Deterministic stand-in without model weights, for tests and local UI work.

    A uniformly coloured image yields no detections, so the "no damage" path can be
    exercised; any other image yields the same two detections.
    """

    version = "dummy"

    def detect(self, image: Image) -> list[Detection]:
        if image.size == 0 or float(image.std()) == 0.0:
            return []
        return [
            make_detection(DamageClass.D40, 0.91, (0.40, 0.55, 0.62, 0.80)),
            make_detection(DamageClass.D00, 0.67, (0.10, 0.20, 0.18, 0.90)),
        ]


def create_backend(args: DetectorArgs) -> DetectorBackend:
    match args.backend:
        case "dummy":
            return DummyDetectorBackend()


@serve.deployment
class Detector:
    def __init__(self, args: DetectorArgs) -> None:
        self._backend = create_backend(args)

    def detect(self, image: Image) -> DetectorOutput:
        # Sync method: Serve runs it in a thread pool, so inference does not block the
        # replica's event loop (health checks keep responding).
        return DetectorOutput(self._backend.detect(image), self._backend.version)
