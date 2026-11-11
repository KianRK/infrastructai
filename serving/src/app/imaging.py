"""Decoding of uploaded images. Hardened upload validation follows with the security work."""

from __future__ import annotations

import io

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageOps, UnidentifiedImageError


class InvalidImageError(ValueError):
    pass


def decode_image(data: bytes, max_pixels: int) -> NDArray[np.uint8]:
    """Decode to an RGB array of shape (H, W, 3), honouring the EXIF orientation."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            if width * height > max_pixels:
                raise InvalidImageError(f"image is too large ({width}x{height} pixels)")
            # Phone photos are often stored rotated; boxes must match what the user sees.
            upright = ImageOps.exif_transpose(image).convert("RGB")
    except InvalidImageError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise InvalidImageError("file is not a readable image") from exc
    return np.asarray(upright, dtype=np.uint8)
