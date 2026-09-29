from io import BytesIO
import warnings

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from backend.orchestrator.state_machine import WorkflowError

MAX_IMAGE_PIXELS = 12_000_000
MAX_IMAGE_SIDE = 8192


def decode_image(data: bytes, *, mask: bool = False) -> Image.Image:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if image.width * image.height > MAX_IMAGE_PIXELS or max(image.size) > MAX_IMAGE_SIDE:
                    raise WorkflowError("Image exceeds 12 megapixels or 8192 pixels per side.")
                if mask and image.format != "PNG":
                    raise WorkflowError("Manual mask must be a PNG image.")
                if not mask and image.format not in {"PNG", "JPEG", "WEBP"}:
                    raise WorkflowError("Scene must be PNG, JPEG, or WebP.")
                image.load()
                if mask:
                    # Gray RGB exports are accepted, but alpha cannot silently select transparent pixels.
                    if "A" in image.getbands() or "transparency" in image.info:
                        rgba = np.asarray(image.convert("RGBA"))
                        if np.any(rgba[:, :, 3] != 255):
                            raise WorkflowError("Mask must be opaque grayscale PNG (0/255).")
                    rgb = np.asarray(image.convert("RGB"))
                    if np.any(rgb[:, :, 0] != rgb[:, :, 1]) or np.any(rgb[:, :, 1] != rgb[:, :, 2]):
                        raise WorkflowError("Mask must be grayscale, not a colored overlay.")
                    return image.convert("L")
                return ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise WorkflowError("Could not decode a supported image.") from exc


def validate_binary_mask(mask: Image.Image, size: tuple[int, int]) -> int:
    if mask.size != size:
        raise WorkflowError(f"Mask dimensions must be exactly {size[0]} x {size[1]}.")
    pixels = np.asarray(mask)
    if mask.mode != "L" or not np.isin(pixels, [0, 255]).all():
        raise WorkflowError("Mask must contain only grayscale values 0 and 255.")
    selected = int(np.count_nonzero(pixels))
    if selected == 0:
        raise WorkflowError("Mask is empty. Draw a welding region before confirming.")
    return selected


def create_mask_overlay(image: Image.Image, mask: Image.Image, opacity: float = 0.45) -> Image.Image:
    """Produce a separate RGB conditioning preview; never mutate the binary mask."""
    validate_binary_mask(mask, image.size)
    if not 0 <= opacity <= 1:
        raise ValueError("Opacity must be between 0 and 1.")
    alpha = mask.point(lambda value: round(value * opacity))
    return Image.composite(Image.new("RGB", image.size, (244, 71, 85)), image.convert("RGB"), alpha)
