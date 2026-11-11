"""Deterministic, group-stratified train/val/test split."""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence

from rdd.config import SplitConfig

SPLITS = ("train", "val", "test")


def split_group(items: Sequence[str], cfg: SplitConfig) -> dict[str, list[str]]:
    """Split one group of item ids. The result depends only on the set of ids and the seed."""
    ordered = sorted(items)  # independent of file-system listing order
    random.Random(cfg.seed).shuffle(ordered)  # noqa: S311 - not security related
    n = len(ordered)
    n_val = round(n * cfg.val)
    n_test = round(n * cfg.test)
    n_train = n - n_val - n_test
    return {
        "train": ordered[:n_train],
        "val": ordered[n_train : n_train + n_val],
        "test": ordered[n_train + n_val :],
    }


def stratified_split(groups: Mapping[str, Sequence[str]], cfg: SplitConfig) -> dict[str, list[str]]:
    """Split every group (country) separately so each split keeps the country mix."""
    result: dict[str, list[str]] = {name: [] for name in SPLITS}
    for group in sorted(groups):
        for name, ids in split_group(groups[group], cfg).items():
            result[name].extend(ids)
    return result
