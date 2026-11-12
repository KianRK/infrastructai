import json
from pathlib import Path

import yaml
from PIL import Image

from rdd.config import DataConfig
from rdd.prepare import prepare


def add_item(raw: Path, country: str, index: int, size: tuple[int, int], objects: str = "") -> str:
    item_id = f"{country}_{index:06d}"
    base = raw / country / "train"
    (base / "images").mkdir(parents=True, exist_ok=True)
    (base / "annotations/xmls").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, "gray").save(base / "images" / f"{item_id}.jpg")
    (base / "annotations/xmls" / f"{item_id}.xml").write_text(
        f"<annotation><filename>{item_id}.jpg</filename>"
        f"<size><width>{size[0]}</width><height>{size[1]}</height></size>{objects}</annotation>"
    )
    return item_id


def obj(name: str, xmin: int, ymin: int, xmax: int, ymax: int) -> str:
    return (
        f"<object><name>{name}</name><bndbox><xmin>{xmin}</xmin><ymin>{ymin}</ymin>"
        f"<xmax>{xmax}</xmax><ymax>{ymax}</ymax></bndbox></object>"
    )


def find(processed: Path, kind: str, item_id: str, suffix: str) -> Path:
    (match,) = processed.glob(f"{kind}/*/{item_id}{suffix}")
    return match


def test_prepare_builds_yolo_dataset(data_config: DataConfig) -> None:
    raw, processed = data_config.paths.raw, data_config.paths.processed
    for i in range(8):
        add_item(raw, "Aland", i, (80, 60), obj("D00", 20, 15, 60, 45))
    large = add_item(raw, "Borduria", 0, (400, 200), obj("D10", 0, 0, 200, 100))
    mixed = add_item(
        raw, "Borduria", 1, (80, 60), obj("D43", 1, 1, 9, 9) + obj("D10", 0, 0, 40, 30)
    )
    background = add_item(raw, "Borduria", 2, (80, 60))
    for i in range(3, 5):
        add_item(raw, "Borduria", i, (80, 60))

    stats = prepare(data_config, workers=2)

    # Every image has exactly one label file in the same split.
    images = sorted(
        p.relative_to(processed / "images").with_suffix("")
        for p in (processed / "images").rglob("*.jpg")
    )
    labels = sorted(
        p.relative_to(processed / "labels").with_suffix("")
        for p in (processed / "labels").rglob("*.txt")
    )
    assert images == labels
    assert len(images) == 13

    # The oversized image is downscaled; its normalised label is unaffected.
    with Image.open(find(processed, "images", large, ".jpg")) as image:
        assert image.size == (100, 50)
    assert find(processed, "labels", large, ".txt").read_text() == (
        "1 0.250000 0.250000 0.500000 0.500000\n"
    )
    # Unknown classes are dropped but counted; background images get an empty label file.
    assert find(processed, "labels", mixed, ".txt").read_text().startswith("1 ")
    assert find(processed, "labels", background, ".txt").read_text() == ""
    assert stats["dropped_labels"] == {"D43": 1}

    dataset = yaml.safe_load((processed / "dataset.yaml").read_text())
    assert dataset["names"] == {0: "D00", 1: "D10"}
    # Location-independent: split directories are relative to dataset.yaml itself.
    assert "path" not in dataset
    assert (processed / dataset["val"]).is_dir()

    saved = json.loads((processed / "stats.json").read_text())
    total = {c: sum(saved[s]["boxes"][c] for s in ("train", "val", "test")) for c in ("D00", "D10")}
    assert total == {"D00": 8, "D10": 2}
    assert sum(saved[s]["background_images"] for s in ("train", "val", "test")) == 3


def test_prepare_skips_unreadable_items_and_reports_them(data_config: DataConfig) -> None:
    raw = data_config.paths.raw
    for country in ("Aland", "Borduria"):
        for i in range(3):
            add_item(raw, country, i, (80, 60))
    (raw / "Aland/train/annotations/xmls/Aland_000001.xml").write_text("<annotation>")

    stats = prepare(data_config, workers=1)

    skipped = stats["skipped"]
    assert isinstance(skipped, list)
    assert len(skipped) == 1
    assert "Aland_000001.xml" in skipped[0]
    assert len(list(data_config.paths.processed.glob("images/*/*.jpg"))) == 5


def test_prepare_replaces_previous_output(data_config: DataConfig) -> None:
    raw, processed = data_config.paths.raw, data_config.paths.processed
    for country in ("Aland", "Borduria"):
        add_item(raw, country, 0, (80, 60))
    stale = processed / "images/train/stale.jpg"
    stale.parent.mkdir(parents=True)
    stale.touch()

    prepare(data_config, workers=1)
    assert not stale.exists()
