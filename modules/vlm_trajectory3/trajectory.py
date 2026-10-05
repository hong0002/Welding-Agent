from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

import numpy as np


CAMERAS = ("B", "F", "L", "R", "S1", "S2", "S3", "S4", "T")


@dataclass(frozen=True)
class SplitConfig:
    absolute_jump: float = 50.0
    relative_jump_ratio: float = 8.0
    duplicate_epsilon: float = 1e-6


def deduplicate_consecutive(points: np.ndarray, epsilon: float = 1e-6) -> np.ndarray:
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[0] < 2:
        raise ValueError(f"expected (N>=2,D) points, got {points.shape}")
    if not np.isfinite(points).all():
        raise ValueError("trajectory contains a non-finite value")
    distances = np.linalg.norm(np.diff(points, axis=0), axis=1)
    keep = np.concatenate(([True], distances > epsilon))
    result = points[keep]
    if result.shape[0] < 2:
        raise ValueError("trajectory has fewer than two distinct points")
    return result


def split_discontinuous(points: np.ndarray, config: SplitConfig) -> tuple[list[np.ndarray], dict]:
    points = deduplicate_consecutive(points, config.duplicate_epsilon)
    distances = np.linalg.norm(np.diff(points, axis=0), axis=1)
    positive = distances[distances > config.duplicate_epsilon]
    median_step = float(np.median(positive)) if positive.size else 0.0
    threshold = max(config.absolute_jump, median_step * config.relative_jump_ratio)
    break_after = np.flatnonzero(distances > threshold)
    starts = [0, *[int(index + 1) for index in break_after]]
    ends = [*[int(index + 1) for index in break_after], len(points)]
    segments = [points[start:end] for start, end in zip(starts, ends) if end - start >= 2]
    if not segments:
        segments = [points]
    return segments, {
        "median_source_step": median_step,
        "discontinuity_threshold": float(threshold),
        "break_count": int(len(break_after)),
        "max_source_step": float(distances.max()),
    }


def polyline_length(points: np.ndarray) -> float:
    points = np.asarray(points, dtype=np.float64)
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())


def _point_line_distance(point: np.ndarray, start: np.ndarray, end: np.ndarray) -> float:
    vector = end - start
    denominator = float(np.dot(vector, vector))
    if denominator <= 1e-18:
        return float(np.linalg.norm(point - start))
    ratio = float(np.clip(np.dot(point - start, vector) / denominator, 0.0, 1.0))
    projection = start + ratio * vector
    return float(np.linalg.norm(point - projection))


def simplify_to_count(points: np.ndarray, count: int) -> np.ndarray:
    """Keep endpoints and the most shape-informative points, returning exactly count when possible."""
    points = np.asarray(points, dtype=np.float64)
    if count < 2:
        raise ValueError("each segment needs at least two points")
    if len(points) == count:
        return points.copy()

    cumulative = np.concatenate(
        ([0.0], np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1)))
    )
    if len(points) < count:
        targets = np.linspace(0.0, cumulative[-1], count)
        return np.stack(
            [np.interp(targets, cumulative, points[:, axis]) for axis in range(points.shape[1])],
            axis=1,
        )
    maximum_deviation = max(
        _point_line_distance(points[index], points[0], points[-1])
        for index in range(1, len(points) - 1)
    )
    if maximum_deviation <= max(1e-6, cumulative[-1] * 0.005):
        targets = np.linspace(0.0, cumulative[-1], count)
        indices = []
        for target in targets:
            index = int(np.argmin(np.abs(cumulative - target)))
            if not indices or index > indices[-1]:
                indices.append(index)
        indices[0] = 0
        indices[-1] = len(points) - 1
        if len(indices) == count:
            return points[indices]

    selected = {0, len(points) - 1}
    intervals: list[tuple[float, int, int, int]] = []

    def add_interval(left: int, right: int) -> None:
        if right - left <= 1:
            return
        distances = [
            _point_line_distance(points[index], points[left], points[right])
            for index in range(left + 1, right)
        ]
        relative_index = int(np.argmax(distances))
        index = left + 1 + relative_index
        intervals.append((distances[relative_index], left, right, index))

    add_interval(0, len(points) - 1)
    while len(selected) < count and intervals:
        intervals.sort(key=lambda item: (item[0], item[2] - item[1]), reverse=True)
        _, left, right, index = intervals.pop(0)
        if index in selected:
            continue
        selected.add(index)
        add_interval(left, index)
        add_interval(index, right)

    if len(selected) < count:
        targets = np.linspace(0.0, cumulative[-1], count)
        for target in targets:
            selected.add(int(np.argmin(np.abs(cumulative - target))))
            if len(selected) == count:
                break

    ordered = sorted(selected)
    if len(ordered) > count:
        ordered = ordered[: count - 1] + [len(points) - 1]
    return points[ordered]


def allocate_point_budget(segments: list[np.ndarray], target_points: int) -> tuple[list[int], bool]:
    if not segments:
        raise ValueError("at least one segment is required")
    minimum = 2 * len(segments)
    effective_target = max(int(target_points), minimum)
    overflow = effective_target > target_points
    budget = [2 for _ in segments]
    remaining = effective_target - sum(budget)

    lengths = np.asarray([max(polyline_length(segment), 1e-9) for segment in segments])
    while remaining > 0:
        index = max(range(len(segments)), key=lambda i: lengths[i] / budget[i])
        budget[index] += 1
        remaining -= 1
    return budget, overflow


def simplify_segments(segments: Iterable[np.ndarray], target_points: int) -> tuple[list[np.ndarray], dict]:
    clean = [deduplicate_consecutive(np.asarray(segment, dtype=np.float64)) for segment in segments]
    budget, overflow = allocate_point_budget(clean, target_points)
    simplified = [simplify_to_count(segment, count) for segment, count in zip(clean, budget)]
    return simplified, {
        "target_point_count": int(target_points),
        "actual_point_count": int(sum(len(segment) for segment in simplified)),
        "point_budget_overflow": bool(overflow),
        "segment_point_counts": [int(len(segment)) for segment in simplified],
    }


def dominant_direction(points: np.ndarray) -> tuple[str, str, str]:
    displacement = np.asarray(points[-1] - points[0], dtype=np.float64)
    axis_index = int(np.argmax(np.abs(displacement)))
    axes = "xyz" if points.shape[1] >= 3 else "xy"
    if float(abs(displacement[axis_index])) <= 1e-9:
        return "closed_or_negligible", "폐곡선 또는 시작점과 끝점이 가까운 방향", "closed or negligible"
    axis = axes[axis_index]
    positive = displacement[axis_index] > 0
    sign = "positive" if positive else "negative"
    ko_sign = "양의" if positive else "음의"
    return (
        f"{sign}_{axis}",
        f"원본 로봇 좌표계의 {ko_sign} {axis.upper()}축 방향",
        f"the {sign} {axis.upper()} direction of the source robot frame",
    )


def trajectory_shape(points: np.ndarray, interpolation_type: str) -> tuple[str, str, str]:
    name = interpolation_type.strip().lower()
    known = {
        "linear": ("linear", "직선", "straight"),
        "arc": ("arc", "원호", "arc-shaped"),
        "arc_upward": ("arc_upward", "위로 휜 원호", "upward arc-shaped"),
        "corner": ("corner", "모서리를 따르는", "corner-following"),
        "double_linear_centered": ("double_linear_centered", "연결된 이중 직선", "connected double-linear"),
    }
    if name in known:
        return known[name]
    length = polyline_length(points)
    chord = float(np.linalg.norm(points[-1] - points[0]))
    straightness = chord / length if length > 1e-9 else 1.0
    return ("linear", "직선", "straight") if straightness >= 0.98 else ("curved", "곡선", "curved")


def mask_descriptor(
    polylines_by_camera: dict[str, list[list[list[float]]]],
    image_sizes: dict[str, tuple[int, int]],
) -> list[float]:
    values: list[float] = []
    for camera in CAMERAS:
        paths = polylines_by_camera.get(camera, [])
        width, height = image_sizes.get(camera, (1, 1))
        diagonal = math.hypot(width, height)
        valid = [np.asarray(path, dtype=np.float64) for path in paths if len(path) >= 2]
        if not valid:
            values.extend([0.0] * 8)
            continue
        all_points = np.concatenate(valid, axis=0)
        lengths = [polyline_length(path) for path in valid]
        total_length = float(sum(lengths))
        longest = valid[int(np.argmax(lengths))]
        displacement = longest[-1] - longest[0]
        minimum = all_points.min(axis=0)
        maximum = all_points.max(axis=0)
        chord = float(np.linalg.norm(displacement))
        values.extend(
            [
                1.0,
                min(len(valid) / 4.0, 1.0),
                min(total_length / max(diagonal, 1.0), 2.0),
                float((maximum[0] - minimum[0]) / max(width, 1)),
                float((maximum[1] - minimum[1]) / max(height, 1)),
                float(displacement[0] / max(width, 1)),
                float(displacement[1] / max(height, 1)),
                float(chord / total_length) if total_length > 1e-9 else 0.0,
            ]
        )
    return values


def serialize_points(points: np.ndarray, digits: int = 4) -> list[list[float]]:
    return [[round(float(value), digits) for value in row] for row in np.asarray(points)]
