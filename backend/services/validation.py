import math
from typing import Protocol, Sequence

import numpy as np

from backend.schemas import PreviewTrajectory, Scene, ValidationReport
from backend.services.components import MaskComponents


class TrajectoryValidator(Protocol):
    def validate(
        self, trajectory: PreviewTrajectory, scene: Scene, *, components: MaskComponents,
        expected_segments: Sequence[tuple[int, int]],
    ) -> ValidationReport: ...


class DummyTrajectoryValidator:
    def validate(
        self, trajectory: PreviewTrajectory, scene: Scene, *, components: MaskComponents,
        expected_segments: Sequence[tuple[int, int]],
    ) -> ValidationReport:
        errors: list[str] = []
        tolerance = 2
        minimum_ratio = 0.8
        if not trajectory.segments:
            errors.append("Trajectory has no segments.")
        actual = [(segment.segment_id, segment.region_id) for segment in trajectory.segments]
        if actual != list(expected_segments):
            errors.append("Segment/region correspondence does not match the selected regions or rough trajectory.")
        if len({segment.segment_id for segment in trajectory.segments}) != len(trajectory.segments):
            errors.append("Duplicate segment_id.")
        if len({segment.region_id for segment in trajectory.segments}) != len(trajectory.segments):
            errors.append("Each selected region must have exactly one independent weld segment.")
        valid_regions = {region.region_id for region in components.regions}
        if components.labels.shape != (scene.height, scene.width):
            errors.append("Component label dimensions do not match the scene.")
            return ValidationReport(valid=False, errors=errors)
        for segment in trajectory.segments:
            prefix = f"Segment {segment.segment_id} (region {segment.region_id})"
            if segment.region_id not in valid_regions:
                errors.append(f"{prefix} references an unknown or filtered region.")
            if segment.mode != "weld":
                errors.append(f"{prefix} must use weld mode; automatic travel is unsupported.")
            if not segment.points:
                errors.append(f"{prefix} is empty.")
                continue
            near_count = 0
            for index, point in enumerate(segment.points):
                if not math.isfinite(point.x) or not math.isfinite(point.y):
                    errors.append(f"{prefix} point {index} contains NaN/Inf.")
                elif not (0 <= point.x <= scene.width - 1 and 0 <= point.y <= scene.height - 1):
                    errors.append(f"{prefix} point {index} lies outside the image bounds.")
                else:
                    x, y = round(point.x), round(point.y)
                    neighborhood = components.labels[
                        max(0, y - tolerance):min(scene.height, y + tolerance + 1),
                        max(0, x - tolerance):min(scene.width, x + tolerance + 1),
                    ]
                    near_count += int(segment.region_id in valid_regions and np.any(neighborhood == segment.region_id))
            if near_count / len(segment.points) < minimum_ratio:
                errors.append(f"{prefix}: fewer than 80% of points are within 2 px of their own mask component.")
        return ValidationReport(
            valid=not errors, errors=errors, component_sanity_checked=True,
            component_tolerance_px=tolerance, minimum_near_component_ratio=minimum_ratio,
        )
