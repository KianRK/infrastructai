"""Grounded prompt construction: structured findings plus curated reference notes.

The language model never sees the image. It receives (1) an aggregated summary of the
detector output and (2) the reference notes of the detected classes only, and is told to
use nothing else. ``ungrounded_classes`` checks its answer, and ``template_description``
is the deterministic text used when the model is unavailable or fails that check.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Literal, TypedDict

import yaml
from pydantic import BaseModel, ConfigDict

from app.schemas import DAMAGE_CLASS_NAMES, DamageClass, Detection

Severity = Literal["low", "moderate", "high"]
_SEVERITY_ORDER: tuple[Severity, ...] = ("low", "moderate", "high")


class ChatMessage(TypedDict):
    role: Literal["system", "user"]
    content: str


class ReferenceNote(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    appearance: str
    causes: str
    measures: str


@cache
def load_knowledge() -> dict[DamageClass, ReferenceNote]:
    text = resources.files("app").joinpath("knowledge.yaml").read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    return {DamageClass(code): ReferenceNote.model_validate(note) for code, note in raw.items()}


# Words that identify a damage class in generated text.
CLASS_KEYWORDS: dict[DamageClass, tuple[str, ...]] = {
    DamageClass.D00: ("longitudinal",),
    DamageClass.D10: ("transverse",),
    DamageClass.D20: ("alligator", "crocodile"),
    DamageClass.D40: ("pothole",),
}


@dataclass(frozen=True)
class Finding:
    """Everything the model is told about one detected damage class."""

    damage_class: DamageClass
    label: str
    count: int
    max_confidence: float
    area_share: float  # summed box area relative to the image, capped at 1
    largest_extent: float  # longer side of the largest box relative to the image
    positions: tuple[str, ...]
    severity: Severity


def _position(detection: Detection) -> str:
    box = detection.box
    x, y = (box.x_min + box.x_max) / 2, (box.y_min + box.y_max) / 2
    horizontal = "left" if x < 1 / 3 else "right" if x > 2 / 3 else "centre"
    vertical = "upper" if y < 1 / 3 else "lower" if y > 2 / 3 else "middle"
    return f"{vertical} {horizontal}"


def estimate_severity(
    damage_class: DamageClass, count: int, area_share: float, largest_extent: float
) -> Severity:
    """Rough, image-based heuristic. It knows nothing about real-world dimensions.

    Rationale: potholes are a direct hazard and alligator cracking indicates structural
    failure, so neither is ever rated "low"; isolated linear cracks are. More instances
    or more of the image covered raises the rating.
    """
    match damage_class:
        case DamageClass.D40:
            return "high" if count >= 3 or area_share >= 0.03 else "moderate"
        case DamageClass.D20:
            return "high" if area_share >= 0.15 else "moderate"
        case _:
            if count >= 6:
                return "high"
            return "moderate" if count >= 3 or largest_extent >= 0.5 else "low"


def summarise(detections: Sequence[Detection]) -> list[Finding]:
    """Aggregate detections per class, most severe class first."""
    findings = []
    for damage_class in DamageClass:
        group = [d for d in detections if d.damage_class == damage_class]
        if not group:
            continue
        areas = [(d.box.x_max - d.box.x_min) * (d.box.y_max - d.box.y_min) for d in group]
        largest = group[areas.index(max(areas))].box
        area_share = min(sum(areas), 1.0)
        largest_extent = max(largest.x_max - largest.x_min, largest.y_max - largest.y_min)
        findings.append(
            Finding(
                damage_class=damage_class,
                label=DAMAGE_CLASS_NAMES[damage_class],
                count=len(group),
                max_confidence=max(d.confidence for d in group),
                area_share=area_share,
                largest_extent=largest_extent,
                positions=tuple(dict.fromkeys(_position(d) for d in group)),
                severity=estimate_severity(damage_class, len(group), area_share, largest_extent),
            )
        )
    return sorted(findings, key=lambda f: _SEVERITY_ORDER.index(f.severity), reverse=True)


def overall_severity(findings: Sequence[Finding]) -> Severity:
    return max((f.severity for f in findings), key=_SEVERITY_ORDER.index)


_NUMBER_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")


def _plural(count: int, label: str, *, words: bool = False) -> str:
    number = _NUMBER_WORDS[count] if words and count < len(_NUMBER_WORDS) else str(count)
    return f"{number} {label}" if count == 1 else f"{number} {label}s"


def _confidence_level(confidence: float) -> str:
    return "high" if confidence >= 0.7 else "medium" if confidence >= 0.5 else "low"


def _finding_block(number: int, finding: Finding) -> str:
    """One finding as labelled lines; small models copy such fields more reliably than
    they untangle a long sentence."""
    level = _confidence_level(finding.max_confidence)
    lines = [
        f"Finding {number}: {_plural(finding.count, finding.label, words=True)}",
        f"  estimated severity: {finding.severity}",
        f"  position in the image: {', '.join(finding.positions)}",
        f"  share of the image covered, all together: about "
        f"{max(1, round(finding.area_share * 100))}%",
        f"  how sure the detector is: {level} ({finding.max_confidence:.2f})",
    ]
    if level == "low":
        lines.append("  note: uncertain detection, should be verified on site")
    return "\n".join(lines)


SYSTEM_PROMPT = """\
You write short road-condition notes for a road maintenance team, based on the output of \
an automated damage detector.

Rules:
1. Describe only the damage types listed under "Findings". Never mention any other type \
of damage, and never add details (sizes, depths, measurements, weather, place names) that \
are not given.
2. For each finding, say what was found and where in the image, state its estimated \
severity exactly as given, then give its typical causes and the usual repair.
3. Take causes and repairs only from the "Reference notes". Do not add other technical \
claims and do not explain why a severity was assigned.
4. If a finding carries a note that it is uncertain, say that it should be verified.
5. Write plain prose in one or two paragraphs, at most 160 words. No lists, no headings."""

# Appended by code rather than requested from the model, so it is always present.
ESTIMATE_DISCLAIMER = (
    "Severity is an approximate, image-based estimate and does not replace an on-site inspection."
)

NO_DAMAGE_DESCRIPTION = (
    "No road damage was detected in this image. The detector recognises longitudinal, "
    "transverse and alligator cracks and potholes; other defects, or damage that is very "
    "small or poorly lit, may be missed."
)


def _closing_instruction(finding_count: int) -> str:
    # Repeated at the very end because small models weigh the latest instruction most.
    # Fewer sentences per finding when there are many keeps the answer within the token
    # budget (and the response time on CPU bounded).
    sentences = "three" if finding_count == 1 else "two"
    return (
        f"Write the note now: about {sentences} sentences per finding, as one plain "
        "paragraph without any formatting."
    )


_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")


def clean_answer(text: str) -> str:
    """Normalise model output to plain prose.

    Removes markdown the model may add despite the instructions and, if generation hit
    the token limit mid-sentence, drops the unfinished last sentence.
    """
    text = re.sub(r"\*\*|__|`", "", text)
    text = re.sub(r"\bFinding \d+:\s*", "", text)  # echo of the input labels
    text = re.sub(r"(?m)^\s*(?:#{1,6}|[-*\u2022]|\d+[.)])\s+", "", text)
    text = re.sub(r"\s*\n\s*", " ", text).strip()
    if text and text[-1] not in ".!?":
        ends = [m.end() for m in _SENTENCE_END.finditer(text)]
        text = text[: ends[-1]] if ends else ""
    return text


def build_messages(findings: Sequence[Finding]) -> list[ChatMessage]:
    if not findings:
        raise ValueError("no findings: the no-damage case must not be sent to the model")
    knowledge = load_knowledge()
    notes = []
    for finding in findings:
        note = knowledge[finding.damage_class]
        notes.append(
            f"[{finding.label}]\n"
            f"Appearance: {note.appearance}\n"
            f"Typical causes: {note.causes}\n"
            f"Typical repair: {note.measures}"
        )
    user = (
        "Findings (this is all the damage in the image):\n"
        + "\n".join(_finding_block(i, f) for i, f in enumerate(findings, start=1))
        + f"\nOverall estimated severity: {overall_severity(findings)}\n\n"
        + "Reference notes:\n"
        + "\n\n".join(notes)
        + "\n\n"
        + _closing_instruction(len(findings))
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def ungrounded_classes(text: str, findings: Sequence[Finding]) -> list[DamageClass]:
    """Damage classes the text talks about although they were not detected."""
    detected = {f.damage_class for f in findings}
    lowered = text.lower()
    return [
        damage_class
        for damage_class, keywords in CLASS_KEYWORDS.items()
        if damage_class not in detected and any(word in lowered for word in keywords)
    ]


def unmentioned_findings(text: str, findings: Sequence[Finding]) -> list[Finding]:
    """Detected findings the text does not talk about (e.g. cut off by the token limit)."""
    lowered = text.lower()
    return [f for f in findings if not any(w in lowered for w in CLASS_KEYWORDS[f.damage_class])]


def finding_text(finding: Finding) -> str:
    """Deterministic sentences for one finding, from the reference notes."""
    note = load_knowledge()[finding.damage_class]
    verify = (
        " This detection is uncertain and should be verified."
        if finding.max_confidence < 0.5
        else ""
    )
    return (
        f"The detector found {_plural(finding.count, finding.label, words=True)} "
        f"({', '.join(finding.positions)} of the image), with an estimated severity of "
        f"{finding.severity}.{verify} Typical causes: {note.causes} "
        f"Typical repair: {note.measures}"
    )


def template_description(findings: Sequence[Finding]) -> str:
    """Deterministic description assembled from the findings and the reference notes."""
    parts = [finding_text(finding) for finding in findings]
    parts.append(f"Overall estimated severity: {overall_severity(findings)}.")
    parts.append(ESTIMATE_DISCLAIMER)
    return " ".join(parts)
