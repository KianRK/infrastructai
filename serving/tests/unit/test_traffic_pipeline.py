import asyncio
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from app.settings import DummyTrafficArgs, OnnxTrafficArgs
from app.traffic.detector import DummyTrafficBackend, OnnxTrafficBackend
from app.traffic.hub import EventHub, TooManySubscribersError
from app.traffic.pipeline import (
    MAX_LAG_SECONDS,
    SYNTHETIC_STREAMS,
    StreamWorker,
    TrafficService,
    build_workers,
)
from app.traffic.source import Frame, SyntheticSource, VideoFileSource, load_manifest
from tests.media import FPS, write_media_dir, write_traffic_model, write_video

EPOCH = 1_000.0


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def worker(duration: float = 2.0, **settings: Any) -> StreamWorker:
    args = DummyTrafficArgs(max_fps=5, track_min_hits=1, track_count_hits=1, **settings)
    meta = SYNTHETIC_STREAMS[0].model_copy(update={"duration": duration})
    return StreamWorker(meta, SyntheticSource(duration, 5), DummyTrafficBackend(), args, EPOCH)


def test_frames_are_analysed_when_their_time_has_come() -> None:
    stream = worker()
    stream.resync(EPOCH)

    event, wait = stream.advance(EPOCH)  # the frame at t=0 is due
    assert event is not None
    assert event.t == 0.0
    assert {o.label for o in event.objects} >= {"person", "car"}
    assert event.stats.in_view["person"] == 1
    assert event.stats.counted["person"] == 1

    event, wait = stream.advance(EPOCH + 0.05)  # the next one (t=0.2) is not
    assert event is None
    assert wait == pytest.approx(0.15)


def test_the_video_loops_and_objects_are_not_carried_over() -> None:
    stream = worker(duration=0.4)  # two frames: t=0.0 and t=0.2
    stream.resync(EPOCH)
    times: list[float] = []
    ids: list[set[int]] = []
    now = EPOCH
    while len(times) < 4:
        event, wait = stream.advance(now)
        now += wait
        if event is not None:
            times.append(event.t)
            ids.append({o.id for o in event.objects})

    assert times == [0.0, 0.2, 0.0, 0.2]
    assert ids[0] == ids[1]
    assert ids[2].isdisjoint(ids[1])  # the tracker was reset at the jump
    assert stream.position(EPOCH + 0.5) == pytest.approx(0.1)


def test_late_frames_are_dropped_not_queued() -> None:
    stream = worker()
    stream.resync(EPOCH)

    event, wait = stream.advance(EPOCH + MAX_LAG_SECONDS + 0.1)  # frame t=0 is far too late
    assert (event, wait) == (None, 0.0)
    event, _ = stream.advance(EPOCH + MAX_LAG_SECONDS + 0.1)  # t=0.2 is late, but in time
    assert event is not None
    assert event.t == pytest.approx(0.2)
    assert event.stats.dropped_frames == 1


def test_resync_jumps_to_the_live_position() -> None:
    stream = worker(duration=2.0)
    stream.resync(EPOCH + 5.3)  # third loop, 1.3 s in

    event, wait = stream.advance(EPOCH + 5.3)
    assert event is None
    assert wait == pytest.approx(0.1)  # next frame of the file: t=1.4
    event, _ = stream.advance(EPOCH + 5.4)
    assert event is not None
    assert event.t == pytest.approx(1.4)


def test_max_fps_skips_frames_of_the_file() -> None:
    args = DummyTrafficArgs(max_fps=2.5)
    source = SyntheticSource(2.0, 5)
    stream = StreamWorker(SYNTHETIC_STREAMS[0], source, DummyTrafficBackend(), args, EPOCH)
    stream.resync(EPOCH)
    times = []
    now = EPOCH
    while now < EPOCH + 1.0:
        event, wait = stream.advance(now)
        now += wait
        if event is not None:
            times.append(event.t)

    assert times == pytest.approx([0.0, 0.4, 0.8])


def test_video_file_source_reads_and_seeks(tmp_path: Path) -> None:
    write_video(tmp_path / "clip.mp4", seconds=2.0)
    source = VideoFileSource(tmp_path / "clip.mp4")

    assert source.duration == pytest.approx(2.0, abs=0.01)
    first = source.read()
    assert first is not None
    assert first.t == pytest.approx(0.0)
    assert first.image.shape == (48, 64, 3)

    source.seek(1.15)
    frame = source.read()
    assert frame is not None
    assert frame.t == pytest.approx(1.2)  # the first frame at or after the position

    count = 1
    while source.read() is not None:
        count += 1
    assert count == round((2.0 - 1.2) * FPS)


def test_onnx_backend_reports_only_configured_classes(tmp_path: Path) -> None:
    # Model input 64x48 (w x h), frame 128x96: scale 0.5, no padding.
    model = write_traffic_model(
        tmp_path / "traffic.onnx",
        [[16, 12, 48, 36, 0.9, 2], [0, 0, 32, 24, 0.8, 9], [8, 8, 16, 16, 0.2, 0]],
    )
    backend = OnnxTrafficBackend(
        OnnxTrafficArgs(
            backend="onnx", model_uri=str(model), media_dir=tmp_path, classes=("person", "car")
        )
    )

    observations = backend.detect(Frame(0.0, np.zeros((96, 128, 3), dtype=np.uint8)))

    (car,) = observations  # the traffic light is not wanted, the person below the threshold
    assert car.label == "car"
    assert car.box == pytest.approx((0.25, 0.25, 0.75, 0.75))


def test_unknown_class_in_the_config_fails_at_startup(tmp_path: Path) -> None:
    model = write_traffic_model(tmp_path / "traffic.onnx", [[0, 0, 0, 0, 0, 0]])
    args = OnnxTrafficArgs(
        backend="onnx", model_uri=str(model), media_dir=tmp_path, classes=("tram",)
    )
    with pytest.raises(ValueError, match="tram"):
        OnnxTrafficBackend(args)


def test_missing_media_is_reported_clearly(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match=r"prepare\.py"):
        load_manifest(tmp_path)


@pytest.mark.anyio
async def test_service_analyses_only_while_somebody_asks(tmp_path: Path) -> None:
    media = write_media_dir(tmp_path / "media", seconds=1.0)
    model = write_traffic_model(tmp_path / "traffic.onnx", [[16, 12, 48, 36, 0.9, 2]])
    args = OnnxTrafficArgs(
        backend="onnx",
        model_uri=str(model),
        media_dir=media,
        idle_seconds=0.5,
        track_min_hits=1,
        track_count_hits=1,
    )
    workers, backend = build_workers(args, epoch=0.0)
    service = TrafficService(args, workers, backend)

    described = service.describe()
    assert [s.id for s in described.streams] == ["test-street"]
    assert described.streams[0].video_url == "/api/traffic/streams/test-street/video"
    assert described.detector_version == "traffic"

    first = await service.events_after(0)
    assert first["latest"] >= 1
    event = first["events"][0]
    assert event["stream"] == "test-street"
    assert [o["label"] for o in event["objects"]] == ["car"]

    later = await service.events_after(first["latest"])
    assert all(e["seq"] > first["latest"] for e in later["events"])

    assert service.running
    await asyncio.sleep(1.0)  # nobody asks: the analysis pauses
    service.describe()  # describing does not wake it up
    assert not service.running
    await service.stop()


class FakeTraffic:
    """Stands in for the traffic deployment's ``events_after``."""

    def __init__(self) -> None:
        self.latest = 5
        self.calls: list[int] = []
        self.released = asyncio.Event()

    async def fetch(self, seq: int) -> dict[str, Any]:
        self.calls.append(seq)
        if seq >= self.latest:
            self.released.clear()
            await self.released.wait()
        return {
            "latest": self.latest,
            "events": [{"seq": n} for n in range(seq + 1, self.latest + 1) if seq < 10**9],
        }

    def publish(self) -> None:
        self.latest += 1
        self.released.set()


@pytest.mark.anyio
async def test_hub_gives_every_subscriber_the_new_events_with_one_upstream_poll() -> None:
    traffic = FakeTraffic()
    hub = EventHub(traffic.fetch, max_subscribers=2)
    first, second = hub.subscribe(), hub.subscribe()
    pending = [asyncio.ensure_future(anext(first)), asyncio.ensure_future(anext(second))]
    await asyncio.sleep(0.05)
    assert hub.subscribers == 2

    traffic.publish()  # wakes the initial "where are you" poll
    await asyncio.sleep(0.05)
    traffic.publish()
    batches = await asyncio.wait_for(asyncio.gather(*pending), 2)

    # Only events from after the subscription, the same for both.
    assert batches == [[{"seq": 7}], [{"seq": 7}]]
    assert traffic.calls[0] > 10**9  # the backlog was skipped
    await first.aclose()
    await second.aclose()
    assert hub.subscribers == 0
    traffic.publish()  # lets the upstream poll return and end
    await asyncio.sleep(0.01)


@pytest.mark.anyio
async def test_hub_limits_subscribers_and_sends_heartbeats() -> None:
    traffic = FakeTraffic()
    hub = EventHub(traffic.fetch, max_subscribers=1)
    stream = hub.subscribe(heartbeat_seconds=0.05)

    assert await anext(stream) == []  # nothing happened: an empty batch
    with pytest.raises(TooManySubscribersError):
        await anext(hub.subscribe())
    await stream.aclose()
    traffic.publish()
    await asyncio.sleep(0.01)
