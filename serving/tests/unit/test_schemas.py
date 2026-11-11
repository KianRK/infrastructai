import pytest
from pydantic import ValidationError

from app.schemas import DAMAGE_CLASS_NAMES, BoundingBox, DamageClass


def test_every_damage_class_has_a_label() -> None:
    assert set(DAMAGE_CLASS_NAMES) == set(DamageClass)


@pytest.mark.parametrize(
    "coords",
    [
        {"x_min": 0.5, "y_min": 0.1, "x_max": 0.5, "y_max": 0.9},  # zero width
        {"x_min": 0.6, "y_min": 0.1, "x_max": 0.4, "y_max": 0.9},  # inverted
        {"x_min": 0.1, "y_min": 0.1, "x_max": 1.2, "y_max": 0.9},  # outside the image
    ],
)
def test_degenerate_or_out_of_range_boxes_are_rejected(coords: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        BoundingBox(**coords)
