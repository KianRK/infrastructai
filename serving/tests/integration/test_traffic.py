"""The live-traffic endpoints through the real Serve application (see conftest)."""

import json

import httpx

from app.traffic.schemas import StreamEvent, StreamList

VIDEO = "/api/traffic/streams/test-street/video"


def test_traffic_endpoints_need_a_session(anonymous: httpx.Client) -> None:
    assert anonymous.get("/api/traffic/streams").status_code == 401
    assert anonymous.get(VIDEO).status_code == 401
    assert anonymous.get("/api/traffic/events").status_code == 401


def test_streams_are_listed_with_their_live_position(client: httpx.Client) -> None:
    response = client.get("/api/traffic/streams")

    assert response.status_code == 200
    listed = StreamList.model_validate(response.json())  # response honours the contract
    (stream,) = listed.streams
    assert stream.id == "test-street"
    assert stream.video_url == VIDEO
    assert 0 <= stream.position < stream.duration == 2.0
    assert stream.aspect_ratio == round(64 / 48, 4)
    assert "car" in listed.classes


def test_video_supports_range_requests(client: httpx.Client) -> None:
    whole = client.get(VIDEO)
    assert whole.status_code == 200
    assert whole.headers["content-type"] == "video/mp4"
    assert whole.headers["accept-ranges"] == "bytes"

    part = client.get(VIDEO, headers={"Range": "bytes=10-19"})
    assert part.status_code == 206
    assert part.content == whole.content[10:20]
    assert part.headers["content-range"] == f"bytes 10-19/{len(whole.content)}"


def test_unknown_stream_is_not_found(client: httpx.Client) -> None:
    assert client.get("/api/traffic/streams/..%2Fmanifest.json/video").status_code == 404
    assert client.get("/api/traffic/streams/nope/video").status_code == 404


def test_events_arrive_as_server_sent_events_and_the_connection_ends(
    client: httpx.Client,
) -> None:
    events = []
    with client.stream("GET", "/api/traffic/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        lines = list(response.iter_lines())  # returns: the server closes after 3 s

    assert lines[0] == "retry: 1000"
    events = [
        StreamEvent.model_validate(json.loads(line.removeprefix("data: ")))
        for line in lines
        if line.startswith("data: ")
    ]
    assert len(events) >= 5  # about five per second
    assert [e.seq for e in events] == sorted({e.seq for e in events})
    assert all(e.stream == "test-street" and 0 <= e.t < 2.0 for e in events)
    assert events[-1].stats.in_view == {"car": 1}
    assert events[-1].stats.counted["car"] >= 1
    assert events[-1].stats.analysis_fps > 0
