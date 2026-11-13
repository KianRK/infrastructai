"""Detection deployment. The backend (dummy or ONNX Runtime) is chosen by config."""

from __future__ import annotations

import ast
import logging
import time
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray
from ray import serve

from app import metrics
from app.model_store import resolve_model
from app.schemas import DAMAGE_CLASS_NAMES, BoundingBox, DamageClass, Detection
from app.settings import DetectorArgs, DummyDetectorArgs, OnnxDetectorArgs
from app.vision import letterbox, to_detections

log = logging.getLogger("ray.serve")

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


class OnnxDetectorBackend:
    """The exported detector (NMS included) on ONNX Runtime, CPU."""

    def __init__(self, args: OnnxDetectorArgs) -> None:
        import onnxruntime  # not needed for the dummy backend

        model = resolve_model(args.model_uri, args.tracking_uri)
        options = onnxruntime.SessionOptions()
        if args.threads is not None:
            options.intra_op_num_threads = args.threads
        self._session = onnxruntime.InferenceSession(
            str(model.path), options, providers=["CPUExecutionProvider"]
        )
        model_input = self._session.get_inputs()[0]
        self._input_name = model_input.name
        _, _, height, width = model_input.shape
        if not isinstance(height, int) or height != width:
            raise ValueError(f"expected a fixed square model input, got {model_input.shape}")
        self._size = height
        # Ultralytics stores the class names in the ONNX metadata as a dict literal.
        metadata = self._session.get_modelmeta().custom_metadata_map
        self._class_names: dict[int, str] = ast.literal_eval(metadata["names"])
        self._threshold = args.confidence_threshold
        self.version = model.version
        log.info("detector %s loaded, classes %s", self.version, self._class_names)

    def detect(self, image: Image) -> list[Detection]:
        tensor, box = letterbox(image, self._size)
        (output,) = self._session.run(None, {self._input_name: tensor})
        return to_detections(output[0], box, self._class_names, self._threshold)


def create_backend(args: DetectorArgs) -> DetectorBackend:
    match args:
        case DummyDetectorArgs():
            return DummyDetectorBackend()
        case OnnxDetectorArgs():
            return OnnxDetectorBackend(args)


@serve.deployment
class Detector:
    def __init__(self, args: DetectorArgs) -> None:
        self._backend = create_backend(args)

    def detect(self, image: Image) -> DetectorOutput:
        # Sync method: Serve runs it in a thread pool, so inference does not block the
        # replica's event loop (health checks keep responding).
        started = time.perf_counter()
        detections = self._backend.detect(image)
        metrics.DETECTOR_SECONDS.observe(time.perf_counter() - started)
        for detection in detections:
            metrics.DETECTIONS.inc(tags={"damage_class": detection.damage_class.value})
        return DetectorOutput(detections, self._backend.version)
