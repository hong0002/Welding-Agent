"""Pure offline geometry probe. No simulator script, IK, USD or Isaac execution."""
import ast
import contextlib
import io
import json
from pathlib import Path
import sys

import h5py
import numpy as np


def inspect_fixture(root, h5, obj, sample_id):
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(root))
    # Inspected pure modules: numpy/scipy geometry only. Do not import sample/server.
    # Read the actual native allowlist without importing scipy for a rejected family.
    tree = ast.parse((root / "welding_scene_layout.py").read_text(encoding="utf-8"))
    supported = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                     and any(isinstance(target, ast.Name) and target.id == "SUPPORTED_FIXTURES" for target in node.targets))
    if not isinstance(supported, tuple) or any(not isinstance(prefix, str) for prefix in supported):
        raise ValueError("Invalid native fixture allowlist")
    from welding_workpiece import load_obj_mesh, _obj_connected_components, _pca_component
    v, counts, indices = load_obj_mesh(obj)
    if not np.isfinite(v).all() or min(indices) < 0 or max(indices) >= len(v):
        raise ValueError("Invalid workpiece OBJ")
    components = [_pca_component(v, c) for c in _obj_connected_components(len(v), counts, indices)]
    with h5py.File(h5, "r") as handle:
        poses = np.asarray(handle["trajectory"], dtype=float)
    if poses.ndim != 2 or poses.shape[1] not in (3, 6) or len(poses) < 2 or not np.isfinite(poses).all():
        raise ValueError("Invalid source poses")
    if poses.shape[1] == 3:
        poses = np.column_stack((poses, np.zeros_like(poses)))
    result = dict(sample_id=sample_id, ready=False, supported_families=list(supported),
                  vertex_count=len(v), face_count=len(counts), source_pose_count=len(poses),
                  source_start_norm_mm=float(np.linalg.norm(poses[0, :3])),
                  components=[dict(vertex_count=len(c["indices"]), pca_extents_mm=c["extents"].tolist(),
                                   bounds_mm=[c["points"].min(0).tolist(), c["points"].max(0).tolist()]) for c in components])
    if not sample_id.startswith(supported):
        result.update(blocker="No native handler for this sample/contact seam/fixture approach; no substitute fixture generated.",
                      source_to_scene=None, orientation_available=False)
        return result
    from welding_scene_layout import build_scene
    with contextlib.redirect_stdout(io.StringIO()):
        _, arrays, _ = build_scene(obj, sample_id, poses)
    rigid = arrays["source_to_scene"]
    rotation = rigid[:3, :3]
    if (rigid.shape != (4, 4) or not np.isfinite(rigid).all() or
            not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-8) or
            not np.isclose(np.linalg.det(rotation), 1) or not np.allclose(rigid[3], [0, 0, 0, 1])):
        raise ValueError("Invalid fixture rigid transform")
    result.update(ready=True, source_to_scene=rigid.tolist(), orientation_available=True,
                  placement_is_calibrated=False, ik_collision_playback_checked=False)
    return result


if __name__ == "__main__":
    config = json.load(sys.stdin)
    try:
        result = inspect_fixture(Path(config["root"]), Path(config["h5"]), Path(config["obj"]), config["sample_id"])
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    except Exception:
        # No raw exceptions/foreign stdout exposed; parent reports a bounded failure.
        raise SystemExit(1) from None
