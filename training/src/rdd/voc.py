"""Pascal VOC XML parsing and conversion to YOLO label lines.

Pure functions without file-system access, so the conversion rules are easy to test.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from xml.etree.ElementTree import Element

# defusedxml guards against entity-expansion attacks in XML we did not write ourselves.
from defusedxml.ElementTree import fromstring


class AnnotationError(ValueError):
    """The XML is not a usable VOC annotation."""


@dataclass(frozen=True)
class VocObject:
    name: str
    xmin: float
    ymin: float
    xmax: float
    ymax: float


@dataclass(frozen=True)
class VocAnnotation:
    filename: str
    # Size as declared in the XML; None when the <size> element is missing or invalid.
    size: tuple[int, int] | None
    objects: tuple[VocObject, ...]


def _text(parent: Element, tag: str) -> str:
    child = parent.find(tag)
    if child is None or child.text is None or not child.text.strip():
        raise AnnotationError(f"missing <{tag}>")
    return child.text.strip()


def _number(parent: Element, tag: str) -> float:
    raw = _text(parent, tag)
    try:
        return float(raw)  # RDD2022 contains both integer and float coordinates
    except ValueError as exc:
        raise AnnotationError(f"<{tag}> is not a number: {raw!r}") from exc


def parse_voc(xml_text: str | bytes) -> VocAnnotation:
    """Parse one VOC annotation file. An annotation without objects is valid (background)."""
    try:
        root = fromstring(xml_text)
    except Exception as exc:  # defusedxml raises several unrelated exception types
        raise AnnotationError(f"invalid XML: {exc}") from exc

    size: tuple[int, int] | None = None
    size_el = root.find("size")
    if size_el is not None:
        try:
            width, height = int(_number(size_el, "width")), int(_number(size_el, "height"))
        except AnnotationError:
            width = height = 0
        if width > 0 and height > 0:
            size = (width, height)

    objects = []
    for obj in root.iter("object"):
        box = obj.find("bndbox")
        if box is None:
            raise AnnotationError("<object> without <bndbox>")
        objects.append(
            VocObject(
                name=_text(obj, "name"),
                xmin=_number(box, "xmin"),
                ymin=_number(box, "ymin"),
                xmax=_number(box, "xmax"),
                ymax=_number(box, "ymax"),
            )
        )
    return VocAnnotation(filename=_text(root, "filename"), size=size, objects=tuple(objects))


def to_yolo_lines(
    objects: Sequence[VocObject], width: int, height: int, class_ids: Sequence[str]
) -> list[str]:
    """Convert VOC pixel boxes to YOLO lines: ``class x_center y_center width height`` (0..1).

    - Objects whose class is not in ``class_ids`` are dropped.
    - Boxes are clipped to the image; boxes that are empty after clipping are dropped.
    - Corner order is normalised, so swapped min/max values are tolerated.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"invalid image size {width}x{height}")
    index = {class_id: i for i, class_id in enumerate(class_ids)}

    lines = []
    for obj in objects:
        if obj.name not in index:
            continue
        x0, x1 = sorted((obj.xmin, obj.xmax))
        y0, y1 = sorted((obj.ymin, obj.ymax))
        x0, x1 = max(0.0, x0), min(float(width), x1)
        y0, y1 = max(0.0, y0), min(float(height), y1)
        if x1 <= x0 or y1 <= y0:
            continue
        xc, yc = (x0 + x1) / 2 / width, (y0 + y1) / 2 / height
        w, h = (x1 - x0) / width, (y1 - y0) / height
        lines.append(f"{index[obj.name]} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}")
    return lines
