from typing import Protocol

import numpy as np
from PIL import Image

from backend.schemas import FinalTrajectory, Point2D, RoughTrajectory, StructuredInstruction, TrajectorySegment


class VLAClient(Protocol):
    def refine(
        self, image: Image.Image, mask: Image.Image, rough: RoughTrajectory,
        language: str, instruction: StructuredInstruction,
    ) -> FinalTrajectory: ...


class DummyVLAClient:
    def refine(
        self, image: Image.Image, mask: Image.Image, rough: RoughTrajectory,
        language: str, instruction: StructuredInstruction,
    ) -> FinalTrajectory:
        return FinalTrajectory(
            segments=[TrajectorySegment(
                segment_id=segment.segment_id, region_id=segment.region_id, mode=segment.mode,
                points=self._refine_points(segment.points),
            ) for segment in rough.segments],
            generator="dummy-independent-segment-resample-smooth",
        )

    @staticmethod
    def _refine_points(points: list[Point2D]) -> list[Point2D]:
        """Resample one segment at a time. No joining, travel, or region reassignment."""
        if len(points) < 2:
            return list(points)
        coordinates = np.array([[p.x, p.y] for p in points], dtype=float)
        distance = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(coordinates, axis=0), axis=1))]
        keep = np.r_[True, np.diff(distance) > 0]
        distance, coordinates = distance[keep], coordinates[keep]
        if len(distance) == 1:
            return [Point2D(x=float(coordinates[0, 0]), y=float(coordinates[0, 1]))]
        else:
            targets = np.linspace(0, distance[-1], max(48, len(coordinates)))
            refined = np.column_stack([np.interp(targets, distance, coordinates[:, axis]) for axis in (0, 1)])
            refined[1:-1] = (refined[:-2] + 2 * refined[1:-1] + refined[2:]) / 4
            points = [Point2D(x=float(x), y=float(y)) for x, y in refined]
        return points
