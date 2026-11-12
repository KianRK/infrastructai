"""Validation and decoding of uploaded images.

Uploads are untrusted. Checks, in order: size in bytes, file type by content (the
declared Content-Type and file name are ignored), pixel count from the header before
anything is decoded, then decoding itself.
"""

from __future__ import annotations

import io
import warnings
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageOps, UnidentifiedImageError

from app.settings import UploadArgs

# Pillow format name -> leading bytes. Only these decoders are ever invoked.
_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "JPEG": (b"\xff\xd8\xff",),
    "PNG": (b"\x89PNG\r\n\x1a\n",),
    "WEBP": (b"RIFF",),  # plus "WEBP" at offset 8, checked below
}


class UploadError(ValueError):
    """Base class; ``status`` is the HTTP status the API answers with."""

    status = 400


class FileTooLargeError(UploadError):
    status = 413


class UnsupportedTypeError(UploadError):
    status = 415


class InvalidImageError(UploadError):
    status = 400


@dataclass(frozen=True)
class DecodedImage:
    pixels: NDArray[np.uint8]  # RGB, upright, longer side at most ``max_side``
    width: int  # size of the upright original, as the user sees it
    height: int


def sniff_format(data: bytes) -> str | None:
    for name, prefixes in _SIGNATURES.items():
        if data.startswith(prefixes):
            if name == "WEBP" and data[8:12] != b"WEBP":
                continue
            return name
    return None


def decode_upload(data: bytes, limits: UploadArgs) -> DecodedImage:
    if len(data) > limits.max_bytes:
        raise FileTooLargeError(f"file is larger than {limits.max_bytes // (1024 * 1024)} MB")
    image_format = sniff_format(data)
    if image_format is None:
        raise UnsupportedTypeError("only JPEG, PNG and WebP images are supported")

    try:
        with warnings.catch_warnings():
            # Pillow only warns for moderately oversized images; treat that as an error.
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=[image_format]) as image:
                width, height = image.size  # from the header, nothing decoded yet
                if width * height > limits.max_pixels:
                    megapixels = limits.max_pixels // 1_000_000
                    raise FileTooLargeError(f"image has more than {megapixels} megapixels")
                # JPEG can be decoded directly at reduced size, which bounds memory and
                # time for large photos. No effect for other formats.
                # EXIF orientations 5-8 are the 90-degree rotations: sides are swapped.
                rotated = image.getexif().get(0x0112) in (5, 6, 7, 8)
                image.draft("RGB", (limits.max_side, limits.max_side))
                # Phone photos are often stored rotated; boxes must match what the user sees.
                upright = ImageOps.exif_transpose(image).convert("RGB")
    except UploadError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        # Pillow's own guard, which fires while opening extremely large images.
        megapixels = limits.max_pixels // 1_000_000
        raise FileTooLargeError(f"image has more than {megapixels} megapixels") from exc
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        SyntaxError,  # raised by some Pillow decoders for corrupt files
    ) as exc:
        raise InvalidImageError("file is not a readable image") from exc

    original = (height, width) if rotated else (width, height)
    upright.thumbnail((limits.max_side, limits.max_side), Image.Resampling.BILINEAR)
    return DecodedImage(np.asarray(upright, dtype=np.uint8), original[0], original[1])
