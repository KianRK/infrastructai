"""Public API contract. The frontend's TypeScript types mirror these models."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DamageClass(StrEnum):
    D00 = "D00"
    D10 = "D10"
    D20 = "D20"
    D40 = "D40"


DAMAGE_CLASS_NAMES: dict[DamageClass, str] = {
    DamageClass.D00: "longitudinal crack",
    DamageClass.D10: "transverse crack",
    DamageClass.D20: "alligator crack",
    DamageClass.D40: "pothole",
}


# "llm": written by the language model. "template": deterministic fallback text (model
# unavailable or its answer failed the grounding check). "no_damage": nothing detected.
DescriptionSource = Literal["llm", "template", "no_damage"]

# Rough, image-based rating computed in code (app.prompt.estimate_severity).
Severity = Literal["low", "moderate", "high"]


class _Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BoundingBox(_Schema):
    """Axis-aligned box in coordinates relative to the image size (0..1).

    Relative coordinates let the frontend draw boxes at any display size
    without knowing how the image was resized for inference.
    """

    x_min: float = Field(ge=0, le=1)
    y_min: float = Field(ge=0, le=1)
    x_max: float = Field(ge=0, le=1)
    y_max: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _has_positive_area(self) -> Self:
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ValueError("box must have positive width and height")
        return self


class Detection(_Schema):
    damage_class: DamageClass
    label: str = Field(description="Human-readable class name, e.g. 'pothole'.")
    confidence: float = Field(ge=0, le=1)
    box: BoundingBox


class Recommendation(_Schema):
    """What is usually done about one detected damage type.

    The texts come verbatim from the curated reference notes, not from the language model.
    """

    damage_class: DamageClass
    label: str
    severity: Severity
    needs_verification: bool = Field(
        description="The detector is unsure about this damage type; check it on site."
    )
    usual_repair: str
    typical_causes: str


class AnalysisResponse(_Schema):
    detections: list[Detection]
    description: str = Field(description="Short summary grounded in the detections.")
    recommendations: list[Recommendation] = Field(
        description="One entry per detected damage type, most severe first."
    )
    disclaimer: str | None = Field(
        description="Limits of the assessment; null when nothing was detected."
    )
    description_source: DescriptionSource
    image_width: int = Field(gt=0)
    image_height: int = Field(gt=0)
    detector_version: str
    llm_model: str
