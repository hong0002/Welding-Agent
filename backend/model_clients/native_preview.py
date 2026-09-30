"""Validate native artifacts for a single web view. Never regenerate native trajectories."""
import numpy as np

from backend.schemas import Point2D, RoughTrajectory, TrajectorySegment


def require(condition):
    if not condition:
        raise ValueError("Native artifact cannot satisfy this confirmed web preview")


def to_preview(data, accepted, camera, size, instruction, components):
    rough, plan, refined = data["rough_trajectory"], data["plan"], data["refined_task"]
    require(rough["primary_camera"] == camera and rough["coordinate_frame"] == f"mask_normalized:{camera}")
    require(plan["status"] == refined["status"] == "ready")
    # Native can ground several cameras. Only its chosen primary view has pixel points.
    known_masks = {f"{view}:polyline_{i}" for view, prediction in accepted["predictions"].items()
                   for i, polyline in enumerate(prediction["polylines"]) if len(polyline["points"]) >= 2}
    for values in (plan["grounded_mask_ids"], refined["target_mask_ids"]):
        require(len(values) == len(set(values)) and set(values) <= known_masks)
    polylines = accepted["predictions"][camera]["polylines"]
    region_for_mask = {}
    for index, polyline in enumerate(polylines):
        points = np.asarray([[p["x"], p["y"]] for p in polyline["points"]], dtype=float)
        require(points.ndim == 2 and points.shape[1] == 2 and len(points) >= 2 and np.isfinite(points).all())
        rounded = np.rint(points).astype(int)
        require(np.all(rounded >= 0) and np.all(rounded < np.asarray(size)))
        labels = set(components.labels[rounded[:, 1], rounded[:, 0]].tolist())
        require(len(labels) == 1 and -1 not in labels)
        region_for_mask[f"{camera}:polyline_{index}"] = labels.pop()
    # Two native polylines in one component cannot silently become separate web welds.
    require(len(set(region_for_mask.values())) == len(region_for_mask))
    require(set(region_for_mask.values()) == {r.region_id for r in components.regions})
    segments = rough["segments"]
    ids = [s["segment_id"] for s in segments]
    require(len(ids) == len(set(ids)) == len(region_for_mask))
    require({s["source_mask_id"] for s in segments} == set(region_for_mask))
    decisions = plan["segment_decisions"]
    require(len(decisions) == len(ids) and {d["segment_id"] for d in decisions} == set(ids))
    decisions = {d["segment_id"]: d for d in decisions}
    points_for_id, region_for_id = {}, {}
    for segment in segments:
        sid = segment["segment_id"]
        require(segment["connected_to_next"] is False)
        points = np.asarray(segment["points_pixel"], dtype=float)
        normalized = np.asarray(segment["points_normalized"], dtype=float)
        require(points.ndim == 2 and points.shape[1] == 2 and 2 <= len(points) <= 4096)
        require(normalized.shape == points.shape and np.isfinite(points).all() and np.isfinite(normalized).all())
        require(np.all(points >= 0) and np.all(points < np.asarray(size)))
        require(np.allclose(points / np.asarray(size), normalized, atol=1e-6, rtol=0))
        decision = decisions[sid]
        require(decision["direction"] in ("forward", "reverse") and type(decision["weld_enabled"]) is bool)
        points_for_id[sid] = points[::-1] if decision["direction"] == "reverse" else points
        region_for_id[sid] = region_for_mask[segment["source_mask_id"]]
        require(decision["weld_enabled"] == (region_for_id[sid] in instruction.region_order))
    operations = sorted(plan["operations"], key=lambda op: op["order"])
    require(len({op["order"] for op in operations}) == len(operations))
    require(all(op.get("segment_id") is None or op["segment_id"] in ids for op in operations))
    require(all(op["weld_enabled"] is False for op in operations if op["action"] != "follow_segment"))
    follow = [op for op in operations if op["action"] == "follow_segment"]
    require(all(op["weld_enabled"] is decisions[op["segment_id"]]["weld_enabled"] for op in follow))
    weld_ids = [op["segment_id"] for op in follow if op["weld_enabled"]]
    require(len(weld_ids) == len(set(weld_ids)))
    require([region_for_id[sid] for sid in weld_ids] == instruction.region_order)
    result = []
    for sid in weld_ids:
        segment = next(s for s in segments if s["segment_id"] == sid)
        require(segment["source_mask_id"] in plan["grounded_mask_ids"] and segment["source_mask_id"] in refined["target_mask_ids"])
        points = points_for_id[sid]
        require((tuple(points[0]) < tuple(points[-1])) if instruction.direction == "left_to_right" else (tuple(points[0]) > tuple(points[-1])))
        result.append(TrajectorySegment(segment_id=len(result), region_id=region_for_id[sid],
                                       points=[Point2D(x=float(x), y=float(y)) for x, y in points]))
    return RoughTrajectory(segments=result, generator="vlm_trajectory:native")
