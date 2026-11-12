"""Tiny stand-ins for the prepared videos and the traffic model."""

import json
from pathlib import Path

import av
import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

FPS = 5
MODEL_INPUT = (48, 64)  # height, width


def write_video(path: Path, seconds: float, size: tuple[int, int] = (64, 48)) -> None:
    """An H.264 clip whose frames get brighter over time."""
    width, height = size
    frames = round(seconds * FPS)
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=FPS)
        stream.width, stream.height, stream.pix_fmt = width, height, "yuv420p"
        for index in range(frames):
            image = np.full((height, width, 3), 255 * index // frames, dtype=np.uint8)
            for packet in stream.encode(av.VideoFrame.from_ndarray(image, format="rgb24")):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def write_traffic_model(path: Path, rows: list[list[float]]) -> Path:
    """A model with the exported detector's interface that always returns ``rows``."""
    output = np.array([rows], dtype=np.float32)
    height, width = MODEL_INPUT
    graph = helper.make_graph(
        [helper.make_node("Constant", [], ["output0"], value=numpy_helper.from_array(output))],
        "fake-traffic-detector",
        [helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, height, width])],
        [helper.make_tensor_value_info("output0", TensorProto.FLOAT, list(output.shape))],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 18)])
    model.ir_version = 10
    names = "{0: 'person', 1: 'bicycle', 2: 'car', 3: 'motorcycle', 5: 'bus', 6: 'train', "
    names += "7: 'truck', 9: 'traffic light'}"
    helper.set_model_props(model, {"names": names})
    onnx.save(model, str(path))
    return path


def write_media_dir(directory: Path, seconds: float = 2.0) -> Path:
    """What serving/media/prepare.py produces, for one short stream."""
    directory.mkdir(parents=True, exist_ok=True)
    write_video(directory / "test-street.mp4", seconds)
    write_video(directory / "test-street.analysis.mp4", seconds)
    manifest = [
        {
            "id": "test-street",
            "title": "Test street",
            "location": "Nowhere",
            "attribution": "generated",
            "licence": "CC0 1.0",
            "source_url": "https://example.org/video",
            "duration": seconds,
            "width": 64,
            "height": 48,
        }
    ]
    (directory / "manifest.json").write_text(json.dumps(manifest))
    return directory
