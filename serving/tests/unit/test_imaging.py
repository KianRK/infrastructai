import io

import numpy as np
import pytest
from PIL import Image

from app.imaging import (
    FileTooLargeError,
    InvalidImageError,
    UnsupportedTypeError,
    decode_upload,
    sniff_format,
)
from app.settings import UploadArgs

LIMITS = UploadArgs(max_bytes=200_000, max_pixels=1_000_000, max_side=320)


def encode(image: Image.Image, fmt: str, **kwargs: object) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, fmt, **kwargs)
    return buffer.getvalue()


def photo(width: int = 64, height: int = 48) -> Image.Image:
    rng = np.random.default_rng(0)
    return Image.fromarray(rng.integers(0, 255, (height, width, 3), dtype=np.uint8))


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_supported_formats_decode_to_rgb(fmt: str) -> None:
    decoded = decode_upload(encode(photo(), fmt), LIMITS)
    assert decoded.pixels.shape == (48, 64, 3)
    assert decoded.pixels.dtype == np.uint8
    assert (decoded.width, decoded.height) == (64, 48)


def test_transparent_and_palette_images_become_rgb() -> None:
    rgba = Image.new("RGBA", (10, 10), (255, 0, 0, 128))
    assert decode_upload(encode(rgba, "PNG"), LIMITS).pixels.shape == (10, 10, 3)
    palette = photo().convert("P")
    assert decode_upload(encode(palette, "PNG"), LIMITS).pixels.shape == (48, 64, 3)


@pytest.mark.parametrize(
    "data",
    [
        b"%PDF-1.7 not an image",
        b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
        b"GIF89a" + bytes(20),
        b"RIFF\x00\x00\x00\x00WAVEfmt ",  # RIFF container, but audio
        b"",
    ],
    ids=["pdf", "svg", "gif", "wav", "empty"],
)
def test_other_content_is_unsupported_whatever_it_is_called(data: bytes) -> None:
    assert sniff_format(data) is None
    with pytest.raises(UnsupportedTypeError):
        decode_upload(data, LIMITS)


def test_type_is_decided_by_content_not_by_what_the_client_claims() -> None:
    # A GIF with a JPEG signature glued on would be handed to the JPEG decoder only,
    # which rejects it; the GIF decoder is never invoked.
    disguised = b"\xff\xd8\xff" + encode(photo(), "GIF")
    with pytest.raises(InvalidImageError):
        decode_upload(disguised, LIMITS)


def test_file_over_the_byte_limit_is_rejected() -> None:
    data = encode(photo(), "PNG")
    limits = UploadArgs(max_bytes=len(data) - 1, max_pixels=1_000_000)
    with pytest.raises(FileTooLargeError, match="larger than"):
        decode_upload(data, limits)
    decode_upload(data, UploadArgs(max_bytes=len(data), max_pixels=1_000_000))


@pytest.mark.parametrize("side", [2_000, 20_000], ids=["over-our-limit", "over-pillows-limit"])
def test_decompression_bomb_is_rejected_from_its_header(side: int) -> None:
    # One-bit pixels compress to a few kilobytes: 20000 x 20000 would need 1.2 GB as RGB.
    bomb = encode(Image.new("1", (side, side)), "PNG")
    assert len(bomb) < LIMITS.max_bytes
    with pytest.raises(FileTooLargeError, match="megapixels"):
        decode_upload(bomb, LIMITS)


def test_truncated_file_is_rejected() -> None:
    data = encode(photo(640, 480), "JPEG")
    with pytest.raises(InvalidImageError):
        decode_upload(data[: len(data) // 2], LIMITS)


def test_large_photo_is_downscaled_but_reports_its_original_size() -> None:
    decoded = decode_upload(encode(photo(800, 600), "JPEG", quality=50), LIMITS)
    assert decoded.pixels.shape == (240, 320, 3)
    assert (decoded.width, decoded.height) == (800, 600)


@pytest.mark.parametrize(
    ("orientation", "upright_size"),
    [(1, (800, 600)), (3, (800, 600)), (6, (600, 800)), (8, (600, 800))],
)
def test_exif_orientation_is_applied(orientation: int, upright_size: tuple[int, int]) -> None:
    exif = Image.Exif()
    exif[0x0112] = orientation
    decoded = decode_upload(encode(photo(800, 600), "JPEG", exif=exif, quality=50), LIMITS)

    assert (decoded.width, decoded.height) == upright_size
    height, width = decoded.pixels.shape[:2]
    assert (width > height) == (upright_size[0] > upright_size[1])
