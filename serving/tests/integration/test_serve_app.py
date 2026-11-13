import io

import httpx
import numpy as np
from PIL import Image

from app.prompt import NO_DAMAGE_DESCRIPTION
from app.schemas import AnalysisResponse


def encode(image: Image.Image, fmt: str = "PNG", **kwargs: object) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, fmt, **kwargs)
    return buffer.getvalue()


def road_photo(size: tuple[int, int] = (320, 240)) -> Image.Image:
    rng = np.random.default_rng(0)
    return Image.fromarray(rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8))


def analyze(client: httpx.Client, data: bytes, name: str = "road.png") -> httpx.Response:
    return client.post("/api/analyze", files={"file": (name, data)})


def test_health(client: httpx.Client) -> None:
    response = client.get("/api/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_analyze_composes_detector_and_describer(client: httpx.Client) -> None:
    response = analyze(client, encode(road_photo((320, 240))))

    assert response.status_code == 200
    result = AnalysisResponse.model_validate(response.json())  # response honours the contract
    assert (result.image_width, result.image_height) == (320, 240)
    assert [d.damage_class for d in result.detections] == ["D40", "D00"]
    # The description was produced from the detector's output, i.e. the handles are wired.
    assert "pothole" in result.description
    assert "longitudinal crack" in result.description
    assert result.description_source == "llm"
    assert result.detector_version == "dummy"
    assert result.llm_model == "dummy"


def test_image_without_damage_gets_the_fixed_description(client: httpx.Client) -> None:
    response = analyze(client, encode(Image.new("RGB", (64, 64), "gray")))

    assert response.status_code == 200
    result = AnalysisResponse.model_validate(response.json())
    assert result.detections == []
    assert result.description == NO_DAMAGE_DESCRIPTION
    assert result.description_source == "no_damage"


def test_exif_rotated_photo_is_analysed_upright(client: httpx.Client) -> None:
    # Stored 320x240 with EXIF orientation 6 (rotate 90 degrees): the user sees 240x320.
    image = road_photo((320, 240))
    exif = Image.Exif()
    exif[0x0112] = 6
    response = analyze(client, encode(image, "JPEG", exif=exif), "phone.jpg")

    assert response.status_code == 200
    body = response.json()
    assert (body["image_width"], body["image_height"]) == (240, 320)


def test_non_image_upload_is_rejected(client: httpx.Client) -> None:
    response = analyze(client, b"%PDF-1.7 this is not an image", "report.png")
    assert response.status_code == 415
    assert response.json() == {"detail": "only JPEG, PNG and WebP images are supported"}


def test_oversized_upload_is_rejected(client: httpx.Client) -> None:
    # Valid PNG signature followed by 10 MB + 1 byte: must fail on size, not on content.
    data = b"\x89PNG\r\n\x1a\n" + bytes(10 * 1024 * 1024)
    response = analyze(client, data, "huge.png")
    assert response.status_code == 413


def test_truncated_image_is_rejected(client: httpx.Client) -> None:
    data = encode(road_photo(), "JPEG")
    response = analyze(client, data[: len(data) // 2], "cut.jpg")
    assert response.status_code == 400


def test_missing_file_field_is_a_validation_error(client: httpx.Client) -> None:
    response = client.post("/api/analyze", files={"other": ("a.png", b"x")})
    assert response.status_code == 422


def test_application_metrics_reach_rays_metrics_endpoint(client: httpx.Client) -> None:
    """The path Prometheus reads in the cluster: Ray's per-node metrics port."""
    import time

    import ray

    assert analyze(client, encode(road_photo())).status_code == 200
    port = ray.nodes()[0]["MetricsExportPort"]  # type: ignore[no-untyped-call]
    wanted = (
        "ray_roadscan_detector_inference_seconds_count",
        'ray_roadscan_detections_total{damage_class="D40"',
        'ray_roadscan_description_seconds_count{source="llm"',
        'ray_roadscan_logins_total{result="ok"',
    )
    text = ""
    deadline = time.monotonic() + 45  # Ray reports metrics every few seconds
    while time.monotonic() < deadline:
        text = httpx.get(f"http://127.0.0.1:{port}/metrics", timeout=10).text
        if all(_has(text, name) for name in wanted):
            return
        time.sleep(2)
    missing = [name for name in wanted if not _has(text, name)]
    raise AssertionError(f"not exported: {missing}")


def _has(text: str, wanted: str) -> bool:
    # Ray adds labels of its own in front of ours, so match name and our label separately.
    name, _, label = wanted.partition("{")
    return any(
        line.startswith(name + "{") and label.replace("{", "") in line for line in text.splitlines()
    )
