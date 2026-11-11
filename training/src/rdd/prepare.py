"""Convert the downloaded RDD2022 subsets to the Ultralytics YOLO layout and split them.

Output in ``paths.processed``::

    images/{train,val,test}/<id>.jpg
    labels/{train,val,test}/<id>.txt     one "class xc yc w h" line per box, empty = background
    dataset.yaml                         dataset definition passed to the trainer
    stats.json                           image and box counts per split (used in the model card)

Usage: ``python -m rdd.prepare [--config configs/data.yaml]``
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from PIL import Image

from rdd.config import DataConfig, PrepareConfig
from rdd.split import SPLITS, stratified_split
from rdd.voc import AnnotationError, parse_voc, to_yolo_lines

log = logging.getLogger(__name__)


@dataclass
class ItemResult:
    """What happened to one image; aggregated into stats.json."""

    boxes: Counter[str] = field(default_factory=Counter)
    dropped_labels: Counter[str] = field(default_factory=Counter)
    resized: bool = False
    skipped: str | None = None


def find_items(raw: Path, country: str) -> dict[str, tuple[Path, Path]]:
    """Map item id -> (annotation path, image path) for one country's labelled images."""
    base = raw / country / "train"
    xml_dir, image_dir = base / "annotations" / "xmls", base / "images"
    if not xml_dir.is_dir():
        raise FileNotFoundError(f"{xml_dir} not found; run `python -m rdd.download` first")
    items = {}
    for xml_path in sorted(xml_dir.glob("*.xml")):
        image_path = image_dir / f"{xml_path.stem}.jpg"
        if image_path.exists():
            items[xml_path.stem] = (xml_path, image_path)
        else:
            log.warning("no image for %s, skipping", xml_path.name)
    return items


def _place_image(image: Image.Image, src: Path, dst: Path, cfg: PrepareConfig) -> bool:
    """Write the training image; returns True when it was downscaled."""
    if cfg.max_image_side is not None and max(image.size) > cfg.max_image_side:
        # draft() lets the JPEG decoder downscale while decoding, which is much faster.
        image.draft("RGB", (cfg.max_image_side, cfg.max_image_side))
        resized = image.convert("RGB")
        resized.thumbnail((cfg.max_image_side, cfg.max_image_side), Image.Resampling.LANCZOS)
        resized.save(dst, "JPEG", quality=cfg.jpeg_quality)
        return True
    try:
        os.link(src, dst)  # no extra disk space
    except OSError:  # different file system, or links unsupported
        shutil.copy2(src, dst)
    return False


def process_item(
    xml_path: Path, image_path: Path, image_out: Path, label_out: Path, cfg: DataConfig
) -> ItemResult:
    result = ItemResult()
    try:
        annotation = parse_voc(xml_path.read_bytes())
        with Image.open(image_path) as image:
            # Boxes are in the coordinate space declared in the XML. Normalising with that
            # size keeps labels correct even if the image file has a different resolution.
            width, height = annotation.size or image.size
            lines = to_yolo_lines(annotation.objects, width, height, cfg.class_ids)
            result.resized = _place_image(image, image_path, image_out, cfg.prepare)
    except (AnnotationError, OSError) as exc:
        result.skipped = f"{xml_path.name}: {exc}"
        return result

    label_out.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    for line in lines:
        result.boxes[cfg.class_ids[int(line.split()[0])]] += 1
    known = set(cfg.class_ids)
    result.dropped_labels.update(o.name for o in annotation.objects if o.name not in known)
    return result


def prepare(cfg: DataConfig, workers: int | None = None) -> dict[str, object]:
    out = cfg.paths.processed
    for sub in ("images", "labels"):
        if (out / sub).exists():
            shutil.rmtree(out / sub)  # generated output; rebuilt from raw on every run
        for split in SPLITS:
            (out / sub / split).mkdir(parents=True)

    items: dict[str, tuple[Path, Path]] = {}
    groups: dict[str, list[str]] = {}
    for country in cfg.countries:
        found = find_items(cfg.paths.raw, country)
        groups[country] = list(found)
        items.update(found)
    assignment = stratified_split(groups, cfg.split)

    stats: dict[str, object] = {"seed": cfg.split.seed, "countries": cfg.countries}
    dropped: Counter[str] = Counter()
    skipped: list[str] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for split in SPLITS:
            ids = assignment[split]
            results = list(
                pool.map(
                    lambda item_id, split=split: process_item(
                        *items[item_id],
                        out / "images" / split / f"{item_id}.jpg",
                        out / "labels" / split / f"{item_id}.txt",
                        cfg,
                    ),
                    ids,
                )
            )
            ok = [r for r in results if r.skipped is None]
            skipped.extend(r.skipped for r in results if r.skipped is not None)
            boxes: Counter[str] = Counter()
            for r in ok:
                boxes.update(r.boxes)
                dropped.update(r.dropped_labels)
            stats[split] = {
                "images": len(ok),
                "background_images": sum(1 for r in ok if not r.boxes),
                "resized_images": sum(1 for r in ok if r.resized),
                "boxes": {class_id: boxes[class_id] for class_id in cfg.class_ids},
            }
            log.info("%s: %s", split, stats[split])
    stats["dropped_labels"] = dict(sorted(dropped.items()))
    stats["skipped"] = skipped
    if skipped:
        log.warning("skipped %d unreadable items, see stats.json", len(skipped))

    dataset = {
        "path": str(out.resolve()),
        **{split: f"images/{split}" for split in SPLITS},
        "names": dict(enumerate(cfg.class_ids)),
    }
    (out / "dataset.yaml").write_text(yaml.safe_dump(dataset, sort_keys=False), encoding="utf-8")
    (out / "stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=Path("configs/data.yaml"))
    parser.add_argument("--workers", type=int, default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    prepare(DataConfig.from_yaml(args.config), workers=args.workers)


if __name__ == "__main__":
    main()
