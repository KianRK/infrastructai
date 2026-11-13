import pytest

from app.detector import make_detection
from app.prompt import (
    CLASS_KEYWORDS,
    build_messages,
    clean_answer,
    clean_summary,
    estimate_severity,
    load_knowledge,
    overall_severity,
    reference_note,
    summarise,
    template_summary,
    ungrounded_classes,
    unmentioned_findings,
)
from app.schemas import DamageClass, Detection


def det(
    cls: DamageClass, conf: float, box: tuple[float, float, float, float] = (0.4, 0.4, 0.6, 0.6)
) -> Detection:
    return make_detection(cls, conf, box)


POTHOLES_AND_CRACK = [
    det(DamageClass.D40, 0.91, (0.40, 0.70, 0.60, 0.90)),  # lower centre, 4% of the image
    det(DamageClass.D40, 0.55, (0.05, 0.40, 0.15, 0.50)),  # middle left, 1%
    det(DamageClass.D00, 0.42, (0.80, 0.10, 0.85, 0.30)),  # upper right, low confidence
]


def test_summary_aggregates_per_class() -> None:
    potholes, crack = summarise(POTHOLES_AND_CRACK)

    assert (potholes.damage_class, potholes.count) == (DamageClass.D40, 2)
    assert potholes.max_confidence == 0.91
    assert potholes.area_share == pytest.approx(0.05)
    assert potholes.largest_extent == pytest.approx(0.20)
    assert potholes.positions == ("lower centre", "middle left")
    assert (crack.damage_class, crack.count, crack.positions) == (
        DamageClass.D00,
        1,
        ("upper right",),
    )


def test_most_severe_finding_comes_first_and_sets_the_overall_severity() -> None:
    findings = summarise(POTHOLES_AND_CRACK)
    assert [f.severity for f in findings] == ["high", "low"]
    assert overall_severity(findings) == "high"


@pytest.mark.parametrize(
    ("cls", "count", "area", "extent", "expected"),
    [
        (DamageClass.D40, 1, 0.005, 0.1, "moderate"),  # a pothole is never "low"
        (DamageClass.D40, 1, 0.04, 0.2, "high"),
        (DamageClass.D40, 3, 0.01, 0.1, "high"),
        (DamageClass.D20, 1, 0.02, 0.2, "moderate"),  # structural damage is never "low"
        (DamageClass.D20, 1, 0.20, 0.5, "high"),
        (DamageClass.D00, 1, 0.01, 0.2, "low"),
        (DamageClass.D10, 1, 0.05, 0.8, "moderate"),  # one long crack
        (DamageClass.D00, 4, 0.05, 0.2, "moderate"),
        (DamageClass.D10, 6, 0.10, 0.2, "high"),
    ],
)
def test_severity_heuristic(
    cls: DamageClass, count: int, area: float, extent: float, expected: str
) -> None:
    assert estimate_severity(cls, count, area, extent) == expected


def test_prompt_contains_the_findings_as_stated_facts() -> None:
    system, user = build_messages(summarise(POTHOLES_AND_CRACK))

    assert system["role"] == "system"
    assert "Never mention any other type" in system["content"]
    assert (
        "Finding 1: two potholes\n"
        "  estimated severity: high\n"
        "  position in the image: lower centre, middle left\n"
        "  share of the image covered, all together: about 5%\n"
        "  how sure the detector is: high (0.91)\n"
    ) in user["content"]
    assert (
        "Finding 2: one longitudinal crack\n"
        "  estimated severity: low\n"
        "  position in the image: upper right\n"
        "  share of the image covered, all together: about 1%\n"
        "  how sure the detector is: low (0.42)\n"
        "  note: uncertain detection, should be verified on site\n"
    ) in user["content"]
    assert "Overall estimated severity: high" in user["content"]
    assert user["content"].endswith("at most three short sentences of plain prose.")


def test_prompt_never_names_damage_that_was_not_detected() -> None:
    # The core grounding property: the model cannot copy what it is never shown.
    for detected in DamageClass:
        system, user = build_messages(summarise([det(detected, 0.9)]))
        text = (system["content"] + user["content"]).lower()
        for other, keywords in CLASS_KEYWORDS.items():
            if other is not detected:
                assert not any(word in text for word in keywords), (detected, other)


def test_prompt_carries_no_causes_or_repairs() -> None:
    # They are shown from the reference notes, so the model has nothing to paraphrase.
    knowledge = load_knowledge()
    system, user = build_messages(summarise([det(DamageClass.D20, 0.9)]))
    text = system["content"] + user["content"]
    assert knowledge[DamageClass.D20].measures not in text
    assert knowledge[DamageClass.D20].causes not in text


def test_no_findings_must_not_reach_the_model() -> None:
    with pytest.raises(ValueError, match="no-damage"):
        build_messages([])


def test_every_class_has_a_reference_note_that_names_no_other_class() -> None:
    knowledge = load_knowledge()
    assert set(knowledge) == set(DamageClass)
    for damage_class, note in knowledge.items():
        text = f"{note.appearance} {note.causes} {note.measures}".lower()
        for other, keywords in CLASS_KEYWORDS.items():
            if other is not damage_class:
                assert not any(word in text for word in keywords), (damage_class, other)


def test_grounding_check_flags_undetected_damage_only() -> None:
    findings = summarise([det(DamageClass.D00, 0.9)])
    grounded = "A longitudinal crack runs along the lane; sealing is the usual repair."
    invented = "A longitudinal crack and several Potholes are visible."
    assert ungrounded_classes(grounded, findings) == []
    assert ungrounded_classes(invented, findings) == [DamageClass.D40]


def test_template_summary_is_grounded_and_flags_uncertain_findings() -> None:
    findings = summarise(POTHOLES_AND_CRACK)
    text = template_summary(findings)

    assert "two potholes" in text
    assert "one longitudinal crack" in text
    assert "uncertain and should be verified" in text
    assert "Overall estimated severity: high" in text
    assert ungrounded_classes(text, findings) == []


def test_reference_note_belongs_to_the_finding() -> None:
    (crack,) = summarise([det(DamageClass.D10, 0.9)])
    assert reference_note(crack) is load_knowledge()[DamageClass.D10]


def test_summary_label_is_removed() -> None:
    assert clean_summary("**Summary:** One pothole was found.") == "One pothole was found."
    assert clean_summary("One pothole was found.") == "One pothole was found."


def test_answer_cleanup_removes_markdown_and_input_labels() -> None:
    raw = (
        "**Road Condition Note**\n\n"
        "## Findings\n"
        "1. Finding 1: Two potholes are visible.\n"
        "- They should be patched.\n"
    )
    assert clean_answer(raw) == (
        "Road Condition Note Findings Two potholes are visible. They should be patched."
    )


def test_answer_cut_off_by_the_token_limit_loses_only_the_unfinished_sentence() -> None:
    assert clean_answer("The crack is sealed. The typical repair") == "The crack is sealed."
    assert clean_answer("no sentence end at all") == ""
    assert clean_answer("A confidence of 0.66 is medium.") == "A confidence of 0.66 is medium."


def test_unmentioned_findings_are_identified() -> None:
    findings = summarise(POTHOLES_AND_CRACK)
    (missing,) = unmentioned_findings("Two potholes need prompt repair.", findings)
    assert missing.damage_class is DamageClass.D00
