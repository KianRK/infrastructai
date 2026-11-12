"""Road-user detection on video frames. The backend is chosen by config."""

from __future__ import annotations

import ast
import logging
import math
from typing import Protocol

from app.model_store import resolve_model
from app.settings import OnnxTrafficArgs
from app.traffic.source import Frame
from app.traffic.tracker import Observation
from app.vision import letterbox, to_boxes

log = logging.getLogger("ray.serve")


class TrafficBackend(Protocol):
    version: str

    def detect(self, frame: Frame) -> list[Observation]: ...


class DummyTrafficBackend:
    """Deterministic stand-in without weights: two cars crossing the frame in opposite
    directions and a person standing at the kerb, as a function of the frame time."""

    version = "dummy"

    def detect(self, frame: Frame) -> list[Observation]:
        right = (frame.t / 8.0 + 0.3) % 1.2 - 0.2  # left edge of the car driving to the right
        left = 1.0 - (frame.t / 11.0 + 0.4) % 1.25
        observations = [
            Observation("person", 0.74, (0.05, 0.42, 0.09, 0.62)),
            Observation("car", 0.9, (right, 0.55, right + 0.2, 0.75)),
            Observation("truck", 0.82, (left, 0.3, left + 0.25, 0.5)),
        ]
        return [clipped for o in observations if (clipped := _clip(o)) is not None]


def _clip(observation: Observation) -> Observation | None:
    x_min, y_min, x_max, y_max = observation.box
    x_min, x_max = max(0.0, x_min), min(1.0, x_max)
    if x_max - x_min < 0.02:
        return None  # (almost) outside the frame
    box = (round(x_min, 4), y_min, round(x_max, 4), y_max)
    return Observation(observation.label, observation.confidence, box)


class OnnxTrafficBackend:
    """A COCO-pretrained detector (NMS included) on ONNX Runtime, CPU."""

    def __init__(self, args: OnnxTrafficArgs) -> None:
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
        if not isinstance(height, int) or not isinstance(width, int):
            raise ValueError(f"expected a fixed model input size, got {model_input.shape}")
        self._size = (height, width)
        # Ultralytics stores the class names in the ONNX metadata as a dict literal.
        metadata = self._session.get_modelmeta().custom_metadata_map
        names: dict[int, str] = ast.literal_eval(metadata["names"])
        missing = set(args.classes) - set(names.values())
        if missing:
            raise ValueError(f"the model does not know the classes {sorted(missing)}")
        self._labels = {index: name for index, name in names.items() if name in args.classes}
        self._threshold = args.confidence_threshold
        self.version = model.version
        log.info("traffic detector %s loaded, input %dx%d", self.version, width, height)

    def detect(self, frame: Frame) -> list[Observation]:
        tensor, box = letterbox(frame.image, self._size)
        (output,) = self._session.run(None, {self._input_name: tensor})
        return [
            Observation(self._labels[class_index], confidence, coordinates)
            for class_index, confidence, coordinates in to_boxes(output[0], box, self._threshold)
            if class_index in self._labels and all(map(math.isfinite, coordinates))
        ]
