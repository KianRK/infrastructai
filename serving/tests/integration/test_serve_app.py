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
    assert response.status_code == 400
    assert response.json() == {"detail": "file is not a readable image"}


def test_truncated_image_is_rejected(client: httpx.Client) -> None:
    data = encode(road_photo(), "JPEG")
    response = analyze(client, data[: len(data) // 2], "cut.jpg")
    assert response.status_code == 400


def test_missing_file_field_is_a_validation_error(client: httpx.Client) -> None:
    response = client.post("/api/analyze", files={"other": ("a.png", b"x")})
    assert response.status_code == 422
