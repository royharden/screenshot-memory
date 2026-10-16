"""Bounded source-grid decoding shared by explicit import and region resolution."""

import hashlib
import io
import warnings
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError
from PIL import __version__ as pillow_version

from screenshot_memory.contracts import MAX_IMAGE_BYTES, MAX_IMAGE_PIXELS
from screenshot_memory.shared.docio.identity import canonical_bytes

GRID_POLICY = "pillow-rgba8-source/1"
POLICY = {
    "decoder": "Pillow",
    "version": pillow_version,
    "formats": ["PNG", "JPEG"],
    "pixels": "RGBA8-row-major",
    "orientation": "encoded-grid-no-exif-autorotation",
    "colour": "Pillow-conversion-no-profile-transform",
    "animation": "reject",
    "max_encoded_bytes": MAX_IMAGE_BYTES,
    "max_pixels": MAX_IMAGE_PIXELS,
}
POLICY_SHA = hashlib.sha256(canonical_bytes(POLICY)).hexdigest()
PROCESSING_REVISION = "s7decode/1:" + POLICY_SHA


class ImageDecodeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SourceGrid:
    width: int
    height: int
    rgba8: bytes


def decode_image_bytes(raw: bytes, *, pixel_limit: int = MAX_IMAGE_PIXELS) -> SourceGrid:
    """Verify PNG/JPEG, bound before pixel allocation, and preserve encoded axes.

    A caller may impose a smaller pixel bound, never enlarge the fixed policy.
    No filename, EXIF autorotation, ICC conversion, model or network is involved.
    """
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_IMAGE_BYTES:
        raise ImageDecodeError("image_byte_limit")
    if type(pixel_limit) is not int or not 0 < pixel_limit <= MAX_IMAGE_PIXELS:
        raise ImageDecodeError("image_pixel_limit")
    signature = "PNG" if raw.startswith(b"\x89PNG\r\n\x1a\n") else None
    if raw.startswith(b"\xff\xd8\xff"):
        signature = "JPEG"
    if signature is None:
        raise ImageDecodeError("unsupported_image")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                width, height = image.size
                if image.format != signature or getattr(image, "n_frames", 1) != 1:
                    raise ImageDecodeError("unsupported_image")
                if not 0 < width * height <= pixel_limit:
                    raise ImageDecodeError("image_pixel_limit")
                image.verify()
            with Image.open(io.BytesIO(raw)) as image:
                image.load()
                with image.convert("RGBA") as rgba:
                    return SourceGrid(width, height, rgba.tobytes())
    except ImageDecodeError:
        raise
    except (Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise ImageDecodeError("image_pixel_limit") from None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise ImageDecodeError("invalid_image") from None
