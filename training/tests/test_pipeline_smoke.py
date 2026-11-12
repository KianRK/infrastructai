"""End-to-end smoke test: a few CPU iterations on synthetic data, real MLflow registry."""

from pathlib import Path

import mlflow
import numpy as np
import onnxruntime
import pytest
import yaml
from mlflow import MlflowClient
from PIL import Image, ImageDraw

from rdd.config import TrainConfig
from rdd.pipeline import run_pipeline

pytestmark = pytest.mark.slow

CLASSES = ["D00", "D10", "D20", "D40"]
IMGSZ = 64


def make_dataset(root: Path) -> Path:
    rng = np.random.default_rng(0)
    for split, count in (("train", 8), ("val", 4), ("test", 4)):
        (root / "images" / split).mkdir(parents=True)
        (root / "labels" / split).mkdir(parents=True)
        for i in range(count):
            image = Image.fromarray(rng.integers(90, 130, (IMGSZ, IMGSZ, 3), dtype=np.uint8))
            ImageDraw.Draw(image).rectangle((16, 16, 48, 48), fill=(20, 20, 20))
            image.save(root / "images" / split / f"{split}_{i}.jpg")
            (root / "labels" / split / f"{split}_{i}.txt").write_text(
                f"{i % len(CLASSES)} 0.5 0.5 0.5 0.5\n"
            )
    dataset = {
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "names": dict(enumerate(CLASSES)),
    }
    path = root / "dataset.yaml"
    path.write_text(yaml.safe_dump(dataset))
    return path


def make_config(tmp_path: Path, threshold: float) -> TrainConfig:
    return TrainConfig.model_validate(
        {
            "data": make_dataset(tmp_path / "data"),
            "output_dir": tmp_path / "runs",
            # Model YAML = random initialisation, so nothing is downloaded.
            "model": {"weights": "yolo26n.yaml"},
            "train": {
                "epochs": 1,
                "imgsz": IMGSZ,
                "batch": 4,
                "amp": False,
                "workers": 0,
                "device": "cpu",
                "plots": False,
            },
            "evaluate": {"split": "test"},
            "export": {"max_det": 20},
            "mlflow": {
                "tracking_uri": f"sqlite:///{tmp_path / 'mlflow.db'}",
                "experiment": "smoke",
                "registered_model": "smoke-detector",
            },
            "gate": {"metric": "map50", "threshold": threshold, "alias": "production"},
        }
    )


@pytest.fixture(autouse=True)
def isolated_mlflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    monkeypatch.chdir(tmp_path)  # MLflow writes ./mlartifacts for a SQLite store


def test_pipeline_trains_registers_and_serves_a_loadable_model(tmp_path: Path) -> None:
    cfg = make_config(tmp_path, threshold=0.0)  # an untrained model must pass this gate

    result = run_pipeline(cfg)

    assert result.gate.passed
    client = MlflowClient()
    run = client.get_run(result.run_id)
    assert run.data.tags["quality_gate"] == "passed"
    assert "test/mAP50" in run.data.metrics
    assert "train/box_loss" in run.data.metrics  # per-epoch callback fired
    assert run.data.params["train.imgsz"] == str(IMGSZ)

    # What the serving stack will do: resolve the alias, download, and load with ONNX Runtime.
    version = client.get_model_version_by_alias("smoke-detector", "production")
    assert str(version.version) == result.model_version
    local = Path(mlflow.artifacts.download_artifacts("models:/smoke-detector@production"))
    (onnx_file,) = local.rglob("*.onnx")
    session = onnxruntime.InferenceSession(str(onnx_file), providers=["CPUExecutionProvider"])
    assert session.get_inputs()[0].shape == [1, 3, IMGSZ, IMGSZ]
    # Contract with the serving code: final boxes, NMS already applied.
    image = np.zeros((1, 3, IMGSZ, IMGSZ), dtype=np.float32)
    (output,) = session.run(None, {session.get_inputs()[0].name: image})
    assert output.shape == (1, 20, 6)
    metadata = session.get_modelmeta().custom_metadata_map
    assert all(name in metadata["names"] for name in CLASSES)


def test_pipeline_does_not_register_a_model_below_the_gate(tmp_path: Path) -> None:
    cfg = make_config(tmp_path, threshold=0.99)

    result = run_pipeline(cfg)

    assert not result.gate.passed
    assert result.model_version is None
    client = MlflowClient()
    assert client.get_run(result.run_id).data.tags["quality_gate"] == "failed"
    assert client.search_registered_models() == []
