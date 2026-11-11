"""Description deployment. The backend (dummy, later llama.cpp or vLLM) is chosen by config."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from ray import serve

from app.prompt import NO_DAMAGE_DESCRIPTION, ChatMessage, build_messages
from app.schemas import Detection
from app.settings import LLMArgs


@dataclass(frozen=True)
class DescriberOutput:
    description: str
    model: str


class LLMBackend(Protocol):
    model: str

    def generate(self, messages: Sequence[ChatMessage]) -> str: ...


class DummyLLMBackend:
    """Deterministic stand-in: restates the user message instead of generating text."""

    model = "dummy"

    def generate(self, messages: Sequence[ChatMessage]) -> str:
        user = next(m["content"] for m in messages if m["role"] == "user")
        items = [line.removeprefix("- ") for line in user.splitlines() if line.startswith("- ")]
        return "Dummy description. The image shows: " + "; ".join(items) + "."


def create_backend(args: LLMArgs) -> LLMBackend:
    match args.backend:
        case "dummy":
            return DummyLLMBackend()


@serve.deployment
class Describer:
    def __init__(self, args: LLMArgs) -> None:
        self._backend = create_backend(args)

    def describe(self, detections: list[Detection]) -> DescriberOutput:
        if not detections:
            # Nothing to describe: answer with fixed text rather than asking a language
            # model to write about damage that is not there.
            return DescriberOutput(NO_DAMAGE_DESCRIPTION, self._backend.model)
        text = self._backend.generate(build_messages(detections))
        return DescriberOutput(text.strip(), self._backend.model)
