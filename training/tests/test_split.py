from rdd.config import SplitConfig
from rdd.split import split_group, stratified_split

CFG = SplitConfig(train=0.8, val=0.1, test=0.1, seed=42)


def ids(prefix: str, n: int) -> list[str]:
    return [f"{prefix}_{i:04d}" for i in range(n)]


def test_split_is_a_partition_with_the_configured_sizes() -> None:
    items = ids("x", 1000)
    result = split_group(items, CFG)
    assert {k: len(v) for k, v in result.items()} == {"train": 800, "val": 100, "test": 100}
    assert sorted(result["train"] + result["val"] + result["test"]) == items


def test_split_does_not_depend_on_input_order() -> None:
    # Directory listings are not ordered consistently across machines.
    items = ids("x", 200)
    assert split_group(items, CFG) == split_group(items[::-1], CFG)


def test_seed_changes_the_assignment() -> None:
    items = ids("x", 200)
    other = SplitConfig(train=0.8, val=0.1, test=0.1, seed=43)
    assert split_group(items, CFG)["val"] != split_group(items, other)["val"]


def test_every_country_is_represented_proportionally() -> None:
    groups = {"Japan": ids("Japan", 500), "Czech": ids("Czech", 50)}
    result = stratified_split(groups, CFG)
    for split, share in (("train", 0.8), ("val", 0.1), ("test", 0.1)):
        for country, total in (("Japan", 500), ("Czech", 50)):
            count = sum(1 for item in result[split] if item.startswith(country))
            assert count == round(total * share), (split, country)


def test_tiny_group_keeps_all_items() -> None:
    result = split_group(ids("x", 3), CFG)
    assert sum(len(v) for v in result.values()) == 3
    assert len(result["train"]) >= 1
