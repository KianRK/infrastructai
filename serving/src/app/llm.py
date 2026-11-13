"""Description deployment. The backend (dummy, llama.cpp or vLLM) is chosen by config."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from ray import serve

from app.prompt import (
    ESTIMATE_DISCLAIMER,
    NO_DAMAGE_DESCRIPTION,
    ChatMessage,
    Finding,
    build_messages,
    clean_summary,
    finding_summary,
    needs_verification,
    reference_note,
    summarise,
    template_summary,
    ungrounded_classes,
    unmentioned_findings,
)
from app.schemas import DescriptionSource, Detection, Recommendation
from app.settings import DummyLLMArgs, LlamaCppArgs, LLMArgs, VllmArgs

log = logging.getLogger("ray.serve")


@dataclass(frozen=True)
class DescriberOutput:
    description: str
    recommendations: tuple[Recommendation, ...]
    disclaimer: str | None
    source: DescriptionSource
    model: str


class LLMBackend(Protocol):
    model: str

    def generate(self, messages: Sequence[ChatMessage]) -> str: ...


class DummyLLMBackend:
    """Deterministic stand-in: restates the findings instead of generating text."""

    model = "dummy"

    def generate(self, messages: Sequence[ChatMessage]) -> str:
        user = next(m["content"] for m in messages if m["role"] == "user")
        items = [
            line.split(": ", 1)[1] for line in user.splitlines() if line.startswith("Finding ")
        ]
        return "Dummy description. The image shows: " + ", ".join(items) + "."


class LlamaCppBackend:
    """Quantized GGUF model with llama.cpp on CPU."""

    def __init__(self, args: LlamaCppArgs) -> None:
        from llama_cpp import Llama

        if args.model_path is not None:
            path = str(args.model_path)
        else:
            from huggingface_hub import hf_hub_download

            path = hf_hub_download(args.repo_id, args.filename, revision=args.revision)
        self._llm = Llama(
            model_path=path, n_ctx=args.context_tokens, n_threads=args.threads, verbose=False
        )
        self._args = args
        self.model = args.filename.removesuffix(".gguf")

    def generate(self, messages: Sequence[ChatMessage]) -> str:
        # The chat template stored in the GGUF file is applied by llama.cpp.
        result: Any = self._llm.create_chat_completion(
            messages=list(messages),
            max_tokens=self._args.max_tokens,
            temperature=self._args.temperature,
        )
        return str(result["choices"][0]["message"]["content"] or "")


class VllmBackend:
    """vLLM on a GPU node. Requires the optional ``vllm`` package (GPU image only).

    NOTE: written against the documented vLLM offline-inference API (``LLM.chat``) but not
    exercised in CI or on the default deployment, which has no GPU.
    """

    def __init__(self, args: VllmArgs) -> None:
        from vllm import LLM, SamplingParams  # type: ignore[import-not-found]

        self._llm = LLM(
            model=args.model,
            revision=args.revision,
            max_model_len=args.context_tokens,
            gpu_memory_utilization=args.gpu_memory_utilization,
        )
        self._params = SamplingParams(temperature=args.temperature, max_tokens=args.max_tokens)
        self.model = args.model

    def generate(self, messages: Sequence[ChatMessage]) -> str:
        outputs = self._llm.chat([list(messages)], self._params)
        return str(outputs[0].outputs[0].text)


def create_backend(args: LLMArgs) -> LLMBackend:
    match args:
        case DummyLLMArgs():
            return DummyLLMBackend()
        case LlamaCppArgs():
            return LlamaCppBackend(args)
        case VllmArgs():
            return VllmBackend(args)


def _recommendations(findings: Sequence[Finding]) -> tuple[Recommendation, ...]:
    """One entry per finding, with the texts of its reference note."""
    return tuple(
        Recommendation(
            damage_class=finding.damage_class,
            label=finding.label,
            severity=finding.severity,
            needs_verification=needs_verification(finding),
            usual_repair=reference_note(finding).measures,
            typical_causes=reference_note(finding).causes,
        )
        for finding in findings
    )


def describe(backend: LLMBackend, detections: Sequence[Detection]) -> DescriberOutput:
    """Describe the detections, never inventing damage.

    - No detections: fixed text, the model is not called at all.
    - Model fails, returns nothing, or mentions an undetected damage class: deterministic
      summary built from the same findings.
    - Model leaves out a detected class (typically cut off by the token limit): the
      deterministic sentence for that finding is appended, so nothing detected goes
      unreported.

    The recommendations never depend on the model: one per detected damage type, from the
    reference notes.
    """
    if not detections:
        return DescriberOutput(NO_DAMAGE_DESCRIPTION, (), None, "no_damage", backend.model)

    findings = summarise(detections)
    try:
        text = clean_summary(backend.generate(build_messages(findings)))
    except Exception:
        log.exception("LLM generation failed, using the template summary")
        text = ""
    if text and (invented := ungrounded_classes(text, findings)):
        log.warning("LLM mentioned undetected damage %s, using the template", invented)
        text = ""
    source: DescriptionSource = "llm" if text else "template"
    if not text:
        text = template_summary(findings)
    for finding in unmentioned_findings(text, findings):
        log.warning("LLM left out %s, appending the reference text", finding.label)
        text = f"{text} {finding_summary(finding)}"
    return DescriberOutput(
        text, _recommendations(findings), ESTIMATE_DISCLAIMER, source, backend.model
    )


@serve.deployment
class Describer:
    def __init__(self, args: LLMArgs) -> None:
        self._backend = create_backend(args)

    def describe(self, detections: list[Detection]) -> DescriberOutput:
        return describe(self._backend, detections)
