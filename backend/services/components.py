"""Deterministic 8-connected regions, using NumPy scanlines and union-find only."""
from dataclasses import dataclass

import numpy as np
from PIL import Image

from backend.schemas import BoundingBox, MaskRegion, Point2D
from backend.services.mask_service import validate_binary_mask

DEFAULT_MIN_COMPONENT_AREA = 16


@dataclass
class MaskComponents:
    regions: list[MaskRegion]
    labels: np.ndarray  # int32, original image size; background/noise = -1
    min_component_area: int
    discarded_component_count: int
    discarded_pixels: int


def detect_components(mask: Image.Image, min_component_area: int = DEFAULT_MIN_COMPONENT_AREA) -> MaskComponents:
    if min_component_area < 1:
        raise ValueError("min_component_area must be at least 1.")
    validate_binary_mask(mask, mask.size)
    foreground = np.asarray(mask) == 255
    parents: list[int] = []
    ranks: list[int] = []
    runs: list[tuple[int, int, int]] = []

    def root(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(a: int, b: int) -> None:
        a, b = root(a), root(b)
        if a == b:
            return
        if ranks[a] < ranks[b]:
            a, b = b, a
        parents[b] = a
        if ranks[a] == ranks[b]:
            ranks[a] += 1

    previous: list[int] = []
    for y, row in enumerate(foreground):
        edges = np.flatnonzero(np.diff(np.r_[False, row, False]))
        current: list[int] = []
        cursor = 0
        for x0, stop in zip(edges[::2], edges[1::2]):
            x0, x1 = int(x0), int(stop) - 1
            index = len(runs)
            runs.append((y, x0, x1))
            parents.append(index)
            ranks.append(0)
            current.append(index)
            while cursor < len(previous) and runs[previous[cursor]][2] < x0 - 1:
                cursor += 1
            neighbor = cursor
            while neighbor < len(previous) and runs[previous[neighbor]][1] <= x1 + 1:
                union(index, previous[neighbor])
                neighbor += 1
        previous = current

    # First foreground pixel in raster order determines IDs, independent of union roots.
    groups: dict[int, list[int]] = {}
    for index in range(len(runs)):
        groups.setdefault(root(index), []).append(index)
    labels = np.full(foreground.shape, -1, dtype=np.int32)
    regions: list[MaskRegion] = []
    discarded_count = discarded_pixels = 0
    for region_id, indices in enumerate(groups.values()):
        area = sum(runs[i][2] - runs[i][1] + 1 for i in indices)
        # IDs precede filtering, so a threshold change never renumbers retained regions.
        if area < min_component_area:
            discarded_count += 1
            discarded_pixels += area
            continue
        x_min, y_min, x_max, y_max = mask.width, mask.height, -1, -1
        sum_x = sum_y = 0
        for index in indices:
            y, x0, x1 = runs[index]
            length = x1 - x0 + 1
            labels[y, x0:x1 + 1] = region_id
            x_min, y_min, x_max, y_max = min(x_min, x0), min(y_min, y), max(x_max, x1), max(y_max, y)
            sum_x += (x0 + x1) * length // 2
            sum_y += y * length
        regions.append(MaskRegion(
            region_id=region_id, pixel_area=area,
            bounding_box=BoundingBox(x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max),
            centroid=Point2D(x=sum_x / area, y=sum_y / area),
        ))
    return MaskComponents(regions, labels, min_component_area, discarded_count, discarded_pixels)
