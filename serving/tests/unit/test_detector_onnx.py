"""ONNX backend against a tiny hand-built model with the exported detector's interface."""

from pathlib import Path

import numpy as np
import onnx
import pytest
from onnx import TensorProto, helper, numpy_helper

from app.detector import OnnxDetectorBackend
from app.model_store import RegistryRef, parse_registry_uri, resolve_model
from app.schemas import DamageClass
from app.settings import OnnxDetectorArgs

SIZE = 64


def write_model(path: Path, rows: list[list[float]], names: str) -> Path:
    """A model that ignores its input and always returns ``rows`` (shape 1 x N x 6)."""
    output = np.array([rows], dtype=np.float32)
    graph = helper.make_graph(
        [helper.make_node("Constant", [], ["output0"], value=numpy_helper.from_array(output))],
        "fake-detector",
        [helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, SIZE, SIZE])],
        [helper.make_tensor_value_info("output0", TensorProto.FLOAT, list(output.shape))],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 18)])
    model.ir_version = 10
    helper.set_model_props(model, {"names": names, "imgsz": f"[{SIZE}, {SIZE}]"})
    onnx.save(model, str(path))
    return path


def test_backend_runs_model_and_maps_boxes_to_the_original_image(tmp_path: Path) -> None:
    # 200x100 photo -> scale 0.32, 16 px top/bottom border on the 64 px input.
    path = write_model(
        tmp_path / "detector.onnx",
        [[16, 24, 48, 40, 0.88, 3], [0, 16, 64, 48, 0.15, 0], [0, 0, 0, 0, 0, 0]],
        names="{0: 'D00', 1: 'D10', 2: 'D20', 3: 'D40'}",
    )
    backend = OnnxDetectorBackend(
        OnnxDetectorArgs(backend="onnx", model_uri=str(path), confidence_threshold=0.25)
    )

    detections = backend.detect(np.zeros((100, 200, 3), dtype=np.uint8))

    assert backend.version == "detector"
    (pothole,) = detections  # the 0.15 box is below the threshold
    assert pothole.damage_class is DamageClass.D40
    box = pothole.box
    assert (box.x_min, box.y_min, box.x_max, box.y_max) == pytest.approx((0.25, 0.25, 0.75, 0.75))


def test_missing_model_file_fails_at_startup(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="detector model not found"):
        resolve_model(str(tmp_path / "missing.onnx"))


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        (
            "models:/roadscan-detector@production",
            RegistryRef("roadscan-detector", "production", None),
        ),
        ("models:/roadscan-detector/7", RegistryRef("roadscan-detector", None, "7")),
    ],
)
def test_registry_uri_forms(uri: str, expected: RegistryRef) -> None:
    assert parse_registry_uri(uri) == expected


@pytest.mark.parametrize("uri", ["models:/roadscan-detector", "models:/a/b/c", "models:/@x"])
def test_malformed_registry_uri_is_rejected(uri: str) -> None:
    with pytest.raises(ValueError, match="unsupported model URI"):
        parse_registry_uri(uri)


def test_registry_model_requires_a_tracking_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    with pytest.raises(ValueError, match="MLFLOW_TRACKING_URI"):
        resolve_model("models:/roadscan-detector@production")
