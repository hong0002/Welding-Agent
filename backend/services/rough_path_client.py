from typing import Protocol

import numpy as np
from PIL import Image

from backend.orchestrator.region_selection import resolve_regions
from backend.schemas import Point2D, RoughTrajectory, StructuredInstruction, TrajectorySegment
from backend.services.components import MaskComponents
from backend.services.mask_service import validate_binary_mask


class RoughPathClient(Protocol):
    def predict(
        self, image: Image.Image, mask: Image.Image, instruction: StructuredInstruction, components: MaskComponents, *, language: str = "",
    ) -> RoughTrajectory: ...


class DummyRoughPathClient:
    def predict(
        self, image: Image.Image, mask: Image.Image, instruction: StructuredInstruction, components: MaskComponents, *, language: str = "",
    ) -> RoughTrajectory:
        validate_binary_mask(mask, image.size)
        instruction = resolve_regions(instruction, components.regions)
        metadata = {region.region_id: region for region in components.regions}
        segments = []
        for segment_id, region_id in enumerate(instruction.region_order):
            box = metadata[region_id].bounding_box
            component = components.labels[box.y_min:box.y_max + 1, box.x_min:box.x_max + 1] == region_id
            vertical = instruction.direction in ('top_to_bottom', 'bottom_to_top')
            if vertical:
                component = component.T
            columns = np.flatnonzero(np.any(component, axis=0))
            sampled = columns[np.unique(np.linspace(0, len(columns) - 1, min(32, len(columns))).astype(int))]
            points = []
            for x in sampled:
                rows = np.flatnonzero(component[:, x])
                # Choose an actual foreground pixel, including columns with multiple branches.
                y = rows[(len(rows) - 1) // 2]
                points.append(Point2D(x=float((y if vertical else x) + box.x_min), y=float((x if vertical else y) + box.y_min)))
            if instruction.direction in ("right_to_left", "bottom_to_top"):
                points.reverse()
            segments.append(TrajectorySegment(segment_id=segment_id, region_id=region_id, points=points))
        return RoughTrajectory(segments=segments, generator="dummy-component-row-median" if vertical else "dummy-component-column-median")
