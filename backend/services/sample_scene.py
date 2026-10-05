"""Shared native sample placement and viewport composition. No path generation."""
from pathlib import Path

SCENE_FIELDS = ('workpiece_vertices_world_m', 'workpiece_face_counts', 'workpiece_face_indices',
    'source_to_scene', 'fixture_table_top_m', 'environment_layout', 'environment_floor_z_m',
    'environment_table_center_xy_m', 'environment_table_size_xy_m')


def build_sample_scene(obj, sample, source_poses, *, backend):
    # These are the same read-only native functions called by run_welding_sample.prepare.
    from welding_scene_layout import build_scene
    poses, arrays, report = build_scene(Path(obj), sample, source_poses)
    if backend in {'dataset_stp','dataset_final'}:
        from welding_environment import apply_environment
        poses, arrays, report = apply_environment(poses, arrays, report, layout='stp')
    return poses, arrays, report


def prepare_demo_scene(*, h5, obj, sample, output, backend):
    """Store only scene arrays. H5 XYZ is never exported as Demo targets/playback."""
    import contextlib
    import hashlib
    import io
    import json
    import h5py
    import numpy as np
    h5, obj, output = map(Path, (h5, obj, output))
    with h5py.File(h5, 'r') as handle:
        source = np.asarray(handle['trajectory'], dtype=float)
    poses = np.column_stack((source, np.zeros_like(source))) if source.shape[1] == 3 else source
    with contextlib.redirect_stdout(io.StringIO()):
        _, arrays, report = build_sample_scene(obj, sample, poses, backend=backend)
    scene = {key: arrays[key] for key in SCENE_FIELDS if key in arrays}
    np.savez_compressed(output/'sample_scene.npz', **scene)
    metadata = dict(sample_id=sample, h5=str(h5), obj=str(obj),
        h5_sha256=hashlib.sha256(h5.read_bytes()).hexdigest(),
        obj_sha256=hashlib.sha256(obj.read_bytes()).hexdigest(),
        layout='stp' if backend in {'dataset_stp','dataset_final'} else 'legacy', cad_source='sample_obj',
        scene_builder='welding_scene_layout.build_scene + welding_environment.apply_environment',
        h5_usage='scene placement/orientation metadata only', gt_playback_used=False,
        workpiece_vertices=len(scene['workpiece_vertices_world_m']), environment=report.get('environment'))
    (output/'sample_scene.json').write_text(json.dumps(metadata, allow_nan=False), encoding='utf-8')
    return metadata


def render_sample_scene(stage, native, *, backend, usd_geom, gf):
    """Identical workpiece/environment primitives for Strict and Demo."""
    import numpy as np
    vertices = np.asarray(native['workpiece_vertices_world_m'])
    work = usd_geom.Mesh.Define(stage, '/Workpiece')
    work.CreatePointsAttr([gf.Vec3f(*map(float, p)) for p in vertices])
    work.CreateFaceVertexCountsAttr(native['workpiece_face_counts'].tolist())
    work.CreateFaceVertexIndicesAttr(native['workpiece_face_indices'].tolist())
    work.CreateSubdivisionSchemeAttr('none')
    work.CreateDisplayColorAttr([gf.Vec3f(.5, .56, .61)])
    work.CreateDoubleSidedAttr(True)
    if backend in {'dataset_stp','dataset_final'}:
        from backend.services.preview_environment import stp_primitives
        environment = stp_primitives(native)
    else:
        environment = [('Ground', [0,0,-.025], [3,3,.05]),
            ('DiagnosticTable', [float(vertices[:,0].mean()),float(vertices[:,1].mean()),float(vertices[:,2].min())-.02], [.3,.3,.04])]
    for name, center, scale in environment:
        cube = usd_geom.Cube.Define(stage, '/'+name)
        cube.CreateSizeAttr(1.)
        cube.AddTranslateOp().Set(gf.Vec3d(*map(float, center)))
        cube.AddScaleOp().Set(gf.Vec3f(*map(float, scale)))
        cube.CreateDisplayColorAttr([gf.Vec3f(.14, .18, .21)])
    return vertices


def scene_composition(stage, path_prim, *, backend):
    """Render diagnostics only; adds no admission/readiness or approval gate."""
    paths = dict(robot='/RB10', tool='/Tool/Geometry', workpiece='/Workpiece',
                 table='/ReferenceTable' if backend in {'dataset_stp','dataset_final'} else '/DiagnosticTable',
                 environment='/Ground', path=path_prim)
    return {name+'_visible': bool(stage.GetPrimAtPath(path).IsValid()) for name,path in paths.items()}


def sample_camera():
    # Same overview includes table, pedestal, workpiece, robot and torch in both modes.
    return dict(eye=[2.15,-2.5,1.55], target=[.4,0,.25])
