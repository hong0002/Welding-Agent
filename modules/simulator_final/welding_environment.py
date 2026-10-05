"""Optional measured-environment approximation; not recovered H5 calibration."""
import numpy as np


def apply_environment(poses, arrays, report, layout):
    if layout == 'legacy':
        return poses, arrays, report
    if layout != 'stp':
        raise ValueError(f'Unknown layout: {layout}')
    # STEP -Y maps to simulation +X, STEP +X to simulation +Y.
    # STEP installation plane z=578 mm becomes robot-base z=0.
    vertices = np.asarray(arrays['workpiece_vertices_world_m'])
    center = (vertices.min(0) + vertices.max(0)) / 2
    delta = np.array([.860-center[0], -center[1], -.010-vertices[:, 2].min()])
    poses = poses.copy()
    poses[:, :3] += delta * 1000
    for key in ('workpiece_vertices_world_m', 'cad_contact_curve_world_m'):
        if key in arrays:
            arrays[key] = np.asarray(arrays[key]) + delta
    transform = np.asarray(arrays['source_to_scene']).copy()
    transform[:3, 3] += delta
    arrays.update(source_to_scene=transform, environment_layout=np.asarray('stp'),
                  fixture_table_top_m=np.asarray(-.010),
                  environment_floor_z_m=np.asarray(-.670),
                  environment_table_center_xy_m=np.asarray([.860, 0.]),
                  environment_table_size_xy_m=np.asarray([.500, .800]))
    report['source_to_scene'] = transform.tolist()
    if 'obj_to_world_translation_m' in report:
        report['obj_to_world_translation_m'] = (np.asarray(report['obj_to_world_translation_m'])+delta).tolist()
    report['environment'] = dict(layout='stp', source='12/데이터수집 환경구축.stp',
        accuracy_mm=10, translation_from_legacy_m=delta.tolist(),
        robot_installation_step_mm=[0, 0, 578], table_top_relative_to_base_mm=-10,
        table_center_relative_to_base_mm=[860, 0, -10],
        note='Approximate supports from STEP; sample centered on table. '
             'Existing workpiece orientation retained. H5-to-base calibration remains unknown.')
    print('[LAYOUT] STP reference: table center=(860,0) mm; top=-10 mm; floor=-670 mm', flush=True)
    return poses, arrays, report
