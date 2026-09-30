"""binary-skeleton-chain-v1: explicit, lossy 2D mask-to-polyline adapter.

Zhang-Suen thinning; reject branches, cycles and degenerate components. No graph bridges,
trimming branches, image rescaling, 3D coordinates, or replacement dummy path algorithm.
"""
import time

import numpy as np

from backend.model_clients.contracts import ModelFault
from backend.services.components import MaskComponents


def component_paths(components: MaskComponents, region_order: list[int]) -> list[list[list[float]]]:
    if not 1 <= len(region_order) <= 64:
        raise ModelFault("MODEL_INPUT_INVALID")
    by_id = {r.region_id: r for r in components.regions}
    deadline = time.monotonic() + 15
    output = []
    for region_id in region_order:
        box = by_id[region_id].bounding_box
        source = components.labels[box.y_min:box.y_max + 1, box.x_min:box.x_max + 1] == region_id
        if source.size > 2_000_000:
            raise ModelFault("MODEL_INPUT_INVALID")
        pixels = np.pad(source.astype(np.uint8), 1)
        for _ in range(512):
            if time.monotonic() >= deadline:
                raise ModelFault("MODEL_TIMEOUT")
            changed = False
            for phase in (0, 1):
                p = [pixels[:-2, 1:-1], pixels[:-2, 2:], pixels[1:-1, 2:], pixels[2:, 2:],
                     pixels[2:, 1:-1], pixels[2:, :-2], pixels[1:-1, :-2], pixels[:-2, :-2]]
                neighbors = sum(p)
                transitions = sum(((p[i] == 0) & (p[(i + 1) % 8] == 1)).astype(np.uint8) for i in range(8))
                if phase == 0:
                    condition = (p[0] * p[2] * p[4] == 0) & (p[2] * p[4] * p[6] == 0)
                else:
                    condition = (p[0] * p[2] * p[6] == 0) & (p[0] * p[4] * p[6] == 0)
                remove = (pixels[1:-1, 1:-1] == 1) & (neighbors >= 2) & (neighbors <= 6) & (transitions == 1) & condition
                if remove.any():
                    pixels[1:-1, 1:-1][remove] = 0
                    changed = True
            if not changed:
                break
        else:
            raise ModelFault("MODEL_INPUT_INVALID")
        points = {(int(x), int(y)) for y, x in np.argwhere(pixels[1:-1, 1:-1])}
        if not 2 <= len(points) <= 50_000:
            raise ModelFault("MODEL_INPUT_INVALID")
        graph = {}
        for x, y in points:
            adjacent = []
            for dx, dy in ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)):
                other = (x + dx, y + dy)
                if other not in points:
                    continue
                # Redundant diagonal alongside an orthogonal edge is not a third branch.
                if dx and dy and ((x + dx, y) in points or (x, y + dy) in points):
                    continue
                adjacent.append(other)
            if not 1 <= len(adjacent) <= 2:
                raise ModelFault("MODEL_INPUT_INVALID")
            graph[(x, y)] = adjacent
        ends = sorted(point for point in points if len(graph[point]) == 1)
        if len(ends) != 2:
            raise ModelFault("MODEL_INPUT_INVALID")
        chain = [ends[0]]
        previous = None
        while True:
            next_points = [p for p in graph[chain[-1]] if p != previous]
            if not next_points:
                break
            previous = chain[-1]
            chain.append(next_points[0])
            if len(chain) > len(points):
                raise ModelFault("MODEL_INPUT_INVALID")
        if len(chain) != len(points):
            raise ModelFault("MODEL_INPUT_INVALID")
        output.append([[float(x + box.x_min), float(y + box.y_min)] for x, y in chain])
    return output
