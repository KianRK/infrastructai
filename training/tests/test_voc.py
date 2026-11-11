import pytest

from rdd.voc import AnnotationError, VocObject, parse_voc, to_yolo_lines

CLASSES = ["D00", "D10", "D20", "D40"]

# Mirrors real RDD2022 files: <size> children in varying order, float coordinates.
ANNOTATION = """
<annotation>
  <folder>images</folder>
  <filename>Czech_000001.jpg</filename>
  <size><depth>3</depth><width>600</width><height>400</height></size>
  <object>
    <name>D20</name>
    <bndbox><xmin>150</xmin><ymin>100</ymin><xmax>450</xmax><ymax>300</ymax></bndbox>
  </object>
  <object>
    <name>D00</name>
    <bndbox><xmin>10.5</xmin><ymin>20.25</ymin><xmax>30.5</xmax><ymax>40.75</ymax></bndbox>
  </object>
</annotation>
"""

BACKGROUND = """
<annotation>
  <filename>Czech_001798.jpg</filename>
  <size><depth>3</depth><width>600</width><height>600</height></size>
</annotation>
"""


def box(name: str, xmin: float, ymin: float, xmax: float, ymax: float) -> VocObject:
    return VocObject(name, xmin, ymin, xmax, ymax)


def test_parse_reads_size_and_objects() -> None:
    annotation = parse_voc(ANNOTATION)
    assert annotation.filename == "Czech_000001.jpg"
    assert annotation.size == (600, 400)
    assert annotation.objects == (
        box("D20", 150, 100, 450, 300),
        box("D00", 10.5, 20.25, 30.5, 40.75),
    )


def test_parse_accepts_image_without_damage() -> None:
    annotation = parse_voc(BACKGROUND)
    assert annotation.objects == ()


def test_parse_reports_unusable_size_as_missing() -> None:
    xml = BACKGROUND.replace("<width>600</width>", "<width>0</width>")
    assert parse_voc(xml).size is None


@pytest.mark.parametrize(
    "xml",
    [
        "<annotation><filename>a.jpg</filename><object><name>D00</name></object></annotation>",
        ANNOTATION.replace("<xmin>150</xmin>", "<xmin>abc</xmin>"),
        ANNOTATION.replace("<xmin>150</xmin>", ""),
        "<annotation><filename>a.jpg",
    ],
    ids=["no-bndbox", "non-numeric", "missing-coordinate", "truncated-file"],
)
def test_parse_rejects_malformed_annotations(xml: str) -> None:
    with pytest.raises(AnnotationError):
        parse_voc(xml)


def test_yolo_line_is_normalised_centre_and_size() -> None:
    lines = to_yolo_lines([box("D20", 150, 100, 450, 300)], 600, 400, CLASSES)
    assert lines == ["2 0.500000 0.500000 0.500000 0.500000"]


def test_unknown_classes_are_dropped() -> None:
    objects = [box("D43", 0, 0, 10, 10), box("Repair", 0, 0, 10, 10), box("D40", 0, 0, 60, 40)]
    assert to_yolo_lines(objects, 600, 400, CLASSES) == ["3 0.050000 0.050000 0.100000 0.100000"]


def test_box_is_clipped_to_the_image() -> None:
    # Extends past the right and bottom edges; only the visible part must remain.
    lines = to_yolo_lines([box("D00", 300, 200, 700, 500)], 600, 400, CLASSES)
    assert lines == ["0 0.750000 0.750000 0.500000 0.500000"]


@pytest.mark.parametrize(
    "obj",
    [
        box("D00", 100, 100, 100, 200),  # zero width
        box("D00", 650, 100, 700, 200),  # entirely outside
        box("D00", -50, -50, 0, 0),  # touches the image only at a corner
    ],
)
def test_empty_boxes_are_dropped(obj: VocObject) -> None:
    assert to_yolo_lines([obj], 600, 400, CLASSES) == []


def test_swapped_corners_are_tolerated() -> None:
    swapped = to_yolo_lines([box("D10", 450, 300, 150, 100)], 600, 400, CLASSES)
    assert swapped == to_yolo_lines([box("D10", 150, 100, 450, 300)], 600, 400, CLASSES)


def test_invalid_image_size_is_an_error() -> None:
    with pytest.raises(ValueError, match="invalid image size"):
        to_yolo_lines([], 0, 400, CLASSES)
