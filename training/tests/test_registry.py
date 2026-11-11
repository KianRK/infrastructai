import pytest

from rdd.config import GateConfig
from rdd.evaluate import EvalMetrics
from rdd.registry import check_gate


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
