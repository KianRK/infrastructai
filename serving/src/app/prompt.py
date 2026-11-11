"""Turns detections into chat messages for the LLM."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, TypedDict

from app.schemas import Detection


class ChatMessage(TypedDict):
    role: Literal["system", "user"]
    content: str


SYSTEM_PROMPT = (
    "You are a road maintenance assistant. Describe only the damage listed by the user. "
    "Never mention damage that is not listed."
)

NO_DAMAGE_DESCRIPTION = (
    "No road damage was detected in this image. The detector recognises longitudinal, "
    "transverse and alligator cracks and potholes; other defects, or damage that is very "
    "small or poorly lit, may be missed."
)


def build_messages(detections: Sequence[Detection]) -> list[ChatMessage]:
    """Minimal prompt; grounding with per-class knowledge is added with the real LLM."""
    lines = [f"- {d.label} ({d.damage_class}), confidence {d.confidence:.2f}" for d in detections]
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "Detected damage:\n" + "\n".join(lines)},
    ]
