import numpy as np
import pytest

from app.schemas import DamageClass
from app.vision import PAD_VALUE, Letterbox, letterbox, to_detections

NAMES = {0: "D00", 1: "D10", 2: "D20", 3: "D40"}


def rows(*values: tuple[float, float, float, float, float, float]) -> np.ndarray:
    return np.array(values, dtype=np.float32).reshape(-1, 6)


def test_landscape_image_is_scaled_and_padded_top_and_bottom() -> None:
    image = np.full((100, 200, 3), 255, dtype=np.uint8)

    tensor, box = letterbox(image, 64)

    assert tensor.shape == (1, 3, 64, 64)
    assert tensor.dtype == np.float32
    assert box == Letterbox(scale=0.32, pad_x=0, pad_y=16, width=200, height=100)
    pad = PAD_VALUE / 255
    assert np.allclose(tensor[0, :, :16, :], pad)  # top border
    assert np.allclose(tensor[0, :, 48:, :], pad)  # bottom border
    assert np.allclose(tensor[0, :, 16:48, :], 1.0)  # the image itself, scaled to 0..1


def test_portrait_image_is_padded_left_and_right() -> None:
    _, box = letterbox(np.zeros((400, 100, 3), dtype=np.uint8), 64)
    assert (box.pad_x, box.pad_y) == (24, 0)


def test_channels_stay_rgb() -> None:
    image = np.zeros((64, 64, 3), dtype=np.uint8)
    image[..., 0] = 255  # pure red
    tensor, _ = letterbox(image, 64)
    assert tensor[0, 0].min() == 1.0
    assert tensor[0, 1:].max() == 0.0


@pytest.mark.parametrize("shape", [(480, 640), (1080, 1920), (1920, 1080), (333, 777)])
def test_box_survives_the_round_trip_through_model_coordinates(shape: tuple[int, int]) -> None:
    height, width = shape
    _, box = letterbox(np.zeros((height, width, 3), dtype=np.uint8), 640)
    relative = (0.25, 0.40, 0.75, 0.90)
    # Where the model would report this box on its 640x640 input:
    x1, x2 = (relative[i] * width * box.scale + box.pad_x for i in (0, 2))
    y1, y2 = (relative[i] * height * box.scale + box.pad_y for i in (1, 3))

    (detection,) = to_detections(rows((x1, y1, x2, y2, 0.8, 3)), box, NAMES, 0.25)

    assert detection.damage_class is DamageClass.D40
    assert detection.label == "pothole"
    got = detection.box
    assert (got.x_min, got.y_min, got.x_max, got.y_max) == pytest.approx(relative, abs=1e-5)


def test_padding_rows_and_low_confidence_are_dropped_and_rest_sorted() -> None:
    box = Letterbox(scale=1.0, pad_x=0, pad_y=0, width=640, height=640)
    output = rows(
        (0, 0, 64, 64, 0.30, 0),
        (0, 0, 64, 64, 0.20, 1),  # below the serving threshold
        (0, 0, 64, 64, 0.90, 2),
        (0, 0, 0, 0, 0, 0),  # zero padding up to max_det
    )
    detections = to_detections(output, box, NAMES, 0.25)
    assert [d.damage_class for d in detections] == [DamageClass.D20, DamageClass.D00]
    assert [d.confidence for d in detections] == pytest.approx([0.90, 0.30])


def test_box_reaching_into_the_padding_is_clipped_to_the_image() -> None:
    # 200x100 image on a 64 px input: content occupies y = 16..48.
    box = Letterbox(scale=0.32, pad_x=0, pad_y=16, width=200, height=100)
    (detection,) = to_detections(rows((-5, 10, 70, 32, 0.9, 0)), box, NAMES, 0.25)
    assert (detection.box.x_min, detection.box.y_min, detection.box.x_max) == (0.0, 0.0, 1.0)
    assert detection.box.y_max == pytest.approx(0.5)


def test_box_entirely_in_the_padding_is_dropped() -> None:
    box = Letterbox(scale=0.32, pad_x=0, pad_y=16, width=200, height=100)
    assert to_detections(rows((10, 0, 30, 12, 0.9, 0)), box, NAMES, 0.25) == []


def test_class_unknown_to_the_api_is_skipped() -> None:
    box = Letterbox(scale=1.0, pad_x=0, pad_y=0, width=640, height=640)
    names = {**NAMES, 4: "D50"}
    output = rows((0, 0, 64, 64, 0.9, 4), (0, 0, 64, 64, 0.9, 7))
    assert to_detections(output, box, names, 0.25) == []
