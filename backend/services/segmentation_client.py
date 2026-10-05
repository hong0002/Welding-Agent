from typing import Protocol

from PIL import Image, ImageDraw


class SegmentationClient(Protocol):
    def segment(self, image: Image.Image, *, instruction: str = "") -> Image.Image:
        """Return a same-size L-mode binary mask containing 0/255."""
        ...


class MaskRefinementClient(Protocol):
    def refine(self, image: Image.Image, current_mask: Image.Image, metadata, *, instruction: str) -> Image.Image:
        """Condition on the current binary mask; return raw, unapproved model output.

        Optional capability. Fresh segmentation is never a fallback implementation.
        """
        ...


class DummySegmentationClient:
    def segment(self, image: Image.Image, *, instruction: str = "") -> Image.Image:
        """A synthetic center band for adapter testing, not learned segmentation."""
        width, height = image.size
        mask = Image.new("L", image.size, 0)
        ImageDraw.Draw(mask).rectangle(
            (width // 5, max(0, height // 2 - max(1, height // 40)),
             min(width - 1, width * 4 // 5), min(height - 1, height // 2 + max(1, height // 40))),
            fill=255,
        )
        return mask
