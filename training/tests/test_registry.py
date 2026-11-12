from pathlib import Path
from types import SimpleNamespace
from typing import cast

import mlflow
import onnx
import pytest
from mlflow import MlflowClient
from onnx import TensorProto, helper

from rdd import registry
from rdd.config import GateConfig, TrainConfig
from rdd.evaluate import EvalMetrics
from rdd.registry import check_gate, has_native_registry, register


def metrics(map50: float, map50_95: float) -> EvalMetrics:
    return EvalMetrics(map50=map50, map50_95=map50_95, precision=0, recall=0, per_class={})


@pytest.mark.parametrize(
    ("value", "passed"),
    [(0.49, False), (0.50, True), (0.75, True)],
    ids=["below", "exactly-at-threshold", "above"],
)
def test_gate_compares_configured_metric_with_threshold(value: float, passed: bool) -> None:
    gate = GateConfig(metric="map50", threshold=0.5, alias="production")
    assert check_gate(metrics(map50=value, map50_95=0.0), gate).passed is passed


def test_gate_uses_the_metric_named_in_the_config() -> None:
    # High mAP@0.5 must not satisfy a gate on the stricter mAP@0.5:0.95.
    gate = GateConfig(metric="map50_95", threshold=0.3, alias="production")
    decision = check_gate(metrics(map50=0.9, map50_95=0.2), gate)
    assert not decision.passed
    assert decision.value == 0.2


def test_azure_ml_is_recognised_by_its_tracking_uri() -> None:
    assert has_native_registry("sqlite:///mlflow.db")
    assert has_native_registry("http://127.0.0.1:5000")
    assert not has_native_registry("azureml://swedencentral.api.azureml.ms/mlflow/v1.0/x")


def test_registration_without_aliases_records_the_alias_as_a_model_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The path used on Azure ML, run here against a local store, which supports the
    same plain operations (run artifacts, model versions, tags)."""
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(registry, "has_native_registry", lambda _uri: False)
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path / 'mlflow.db'}")
    mlflow.set_experiment("registry-test")  # not the experiment another test left active
    node = helper.make_node("Identity", ["x"], ["y"])
    graph = helper.make_graph(
        [node],
        "tiny",
        [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1])],
        [helper.make_tensor_value_info("y", TensorProto.FLOAT, [1])],
    )
    onnx_path = tmp_path / "tiny.onnx"
    onnx.save(helper.make_model(graph, opset_imports=[helper.make_opsetid("", 18)]), onnx_path)
    cfg = cast(
        TrainConfig,
        SimpleNamespace(
            mlflow=SimpleNamespace(registered_model="tiny-detector"),
            gate=SimpleNamespace(alias="production"),
        ),
    )

    versions = []
    for _ in range(2):  # the second run finds the registered model already there
        with mlflow.start_run():
            versions.append(register(cfg, onnx_path))

    assert versions == ["1", "2"]
    client = MlflowClient()
    assert client.get_registered_model("tiny-detector").tags == {"alias.production": "2"}
    local = Path(mlflow.artifacts.download_artifacts("models:/tiny-detector/2"))
    assert [p.name for p in local.rglob("*.onnx")] == ["model.onnx"]
