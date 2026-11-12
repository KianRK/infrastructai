from collections.abc import Sequence

import pytest

from app.detector import make_detection
from app.llm import DummyLLMBackend, describe
from app.prompt import ESTIMATE_DISCLAIMER, NO_DAMAGE_DESCRIPTION, ChatMessage
from app.schemas import DamageClass

CRACK = [make_detection(DamageClass.D10, 0.8, (0.1, 0.4, 0.9, 0.5))]


class ScriptedBackend:
    model = "scripted"

    def __init__(self, reply: str | Exception) -> None:
        self.reply = reply
        self.calls: list[Sequence[ChatMessage]] = []

    def generate(self, messages: Sequence[ChatMessage]) -> str:
        self.calls.append(messages)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def test_grounded_answer_is_returned_as_llm_text() -> None:
    backend = ScriptedBackend("  One transverse crack crosses the lane; seal it.\n")
    result = describe(backend, CRACK)
    assert result.description == (
        f"One transverse crack crosses the lane; seal it.\n\n{ESTIMATE_DISCLAIMER}"
    )
    assert (result.source, result.model) == ("llm", "scripted")


def test_no_detections_never_calls_the_model() -> None:
    backend = ScriptedBackend("should not be used")
    result = describe(backend, [])
    assert backend.calls == []
    assert (result.description, result.source) == (NO_DAMAGE_DESCRIPTION, "no_damage")


@pytest.mark.parametrize(
    "reply",
    [
        "A transverse crack and a large pothole are visible.",  # invents a pothole
        "   ",
        RuntimeError("model crashed"),
    ],
    ids=["invented-damage", "empty-answer", "backend-error"],
)
def test_unusable_answer_falls_back_to_the_template(reply: str | Exception) -> None:
    result = describe(ScriptedBackend(reply), CRACK)
    assert result.source == "template"
    assert "one transverse crack" in result.description
    assert "pothole" not in result.description.lower()


def test_dummy_backend_restates_the_findings() -> None:
    result = describe(DummyLLMBackend(), CRACK)
    assert result.source == "llm"
    assert "one transverse crack" in result.description


def test_detected_damage_the_model_left_out_is_still_reported() -> None:
    detections = [*CRACK, make_detection(DamageClass.D40, 0.9, (0.4, 0.7, 0.6, 0.9))]
    backend = ScriptedBackend("One transverse crack crosses the lane. The typical rep")

    result = describe(backend, detections)

    assert result.source == "llm"
    assert result.description.startswith("One transverse crack crosses the lane. The detector")
    assert "found one pothole" in result.description
