import pytest

from app.traffic.tracker import Box, Observation, StreamStatistics, Tracker, iou


def car(x: float, label: str = "car", confidence: float = 0.9) -> Observation:
    return Observation(label, confidence, (x, 0.4, x + 0.2, 0.6))


def test_iou() -> None:
    box: Box = (0.0, 0.0, 0.2, 0.2)
    assert iou(box, box) == pytest.approx(1.0)
    assert iou(box, (0.1, 0.0, 0.3, 0.2)) == pytest.approx(1 / 3)
    assert iou(box, (0.2, 0.0, 0.4, 0.2)) == 0.0  # touching edges do not overlap


def test_a_moving_object_keeps_its_identity_and_is_counted_once() -> None:
    tracker = Tracker(iou_threshold=0.3, max_missed=2, min_hits=3)
    counted: list[str] = []
    seen: list[list[int]] = []
    for step in range(6):
        visible, confirmed = tracker.update([car(0.1 + 0.03 * step)])
        counted += confirmed
        seen.append([track.id for track in visible])

    # Hidden for the first two frames (it could be a false detection), then stable.
    assert seen == [[], [], [1], [1], [1], [1]]
    assert counted == ["car"]


def test_counting_can_wait_longer_than_showing() -> None:
    tracker = Tracker(min_hits=2, count_hits=4)
    results = [tracker.update([car(0.1)]) for _ in range(5)]

    assert [len(visible) for visible, _ in results] == [0, 1, 1, 1, 1]
    assert [confirmed for _, confirmed in results] == [[], [], [], ["car"], []]


def test_two_objects_are_told_apart() -> None:
    tracker = Tracker(min_hits=1)
    tracker.update([car(0.1), car(0.6)])
    # Reported in the other order in the next frame.
    visible, _ = tracker.update([car(0.62), car(0.12)])

    assert {track.id: track.box[0] for track in visible} == {1: 0.12, 2: 0.62}


def test_a_short_gap_does_not_create_a_new_object() -> None:
    tracker = Tracker(max_missed=2, min_hits=1)
    counted = tracker.update([car(0.1)])[1]
    visible, confirmed = tracker.update([])  # missed in one frame
    assert visible == []
    counted += confirmed
    visible, confirmed = tracker.update([car(0.12)])
    counted += confirmed

    assert [track.id for track in visible] == [1]
    assert counted == ["car"]


def test_an_object_that_stays_away_is_forgotten() -> None:
    tracker = Tracker(max_missed=1, min_hits=1)
    tracker.update([car(0.1)])
    tracker.update([])
    tracker.update([])
    visible, confirmed = tracker.update([car(0.1)])

    assert [track.id for track in visible] == [2]
    assert confirmed == ["car"]


def test_the_class_with_the_most_support_wins() -> None:
    tracker = Tracker(min_hits=1)
    tracker.update([car(0.1, "truck", 0.5)])
    tracker.update([car(0.1, "car", 0.9)])
    visible, _ = tracker.update([car(0.1, "truck", 0.3)])

    assert visible[0].label == "car"  # 0.9 against 0.5 + 0.3


def test_reset_drops_objects_but_never_reuses_identifiers() -> None:
    tracker = Tracker(min_hits=1)
    tracker.update([car(0.1)])
    tracker.reset()
    visible, _ = tracker.update([car(0.1)])

    assert [track.id for track in visible] == [2]


def test_statistics_use_sliding_windows() -> None:
    stats = StreamStatistics()
    stats.frame(100.0, 0.02, ["car", "bus"])
    stats.frame(100.2, 0.04, [])
    stats.frame(100.4, 0.03, ["car"])

    assert stats.counted == {"car": 2, "bus": 1}
    assert stats.per_minute == 3
    assert stats.analysis_fps == pytest.approx(5.0)
    assert stats.inference_ms == pytest.approx(30.0)

    stats.frame(161.0, 0.05, [])  # more than a minute later
    assert stats.counted == {"car": 2, "bus": 1}  # totals stay
    assert stats.per_minute == 0
    assert stats.analysis_fps == 0.0
    assert stats.inference_ms == pytest.approx(50.0)
