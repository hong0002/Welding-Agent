"""Explicit bounded offline native registration/preparation audit; no SimulationApp."""
import argparse
import hashlib
import inspect
import json
from pathlib import Path
import platform
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    manifest = json.loads((project/'.cache/simulator-final-audit/e25fdd9d-b8a8-498d-9963-256ac232c481/manifest.json').read_text(encoding='utf-8'))
    sys.path.insert(0, str(args.native.resolve()))
    import h5py
    import numpy as np
    import scipy
    import trimesh
    import welding_contact_fixture as fixture
    from welding_workpiece import load_obj_mesh
    h5 = Path(manifest['h5'])
    teaching = next(p for p in h5.parents if p.name == '로봇티칭데이터')
    obj = teaching.parent/'모델링 데이터'/h5.relative_to(teaching).with_suffix('.obj')
    with h5py.File(h5, 'r') as file:
        source = np.asarray(file['trajectory'], dtype=float)
    prediction = np.load(Path(manifest['prediction'])/'trajectory.npz')['predicted_path_m']
    vertices, counts, indices = load_obj_mesh(obj)
    contact, gap, meshes = fixture.contact_geometry(vertices, counts, indices)
    points = source[np.unique(np.linspace(0,len(source)-1,min(64,len(source))).astype(int)),:3]
    candidates = []
    trace_file = inspect.getsourcefile(fixture.register_path)
    lines, start = inspect.getsourcelines(fixture.register_path)
    target_line = next(start+i for i,line in enumerate(lines) if 'if best is None or score < best[0]:' in line or 'if prefer_registration(' in line)
    def trace(frame, event, arg):
        if frame.f_code.co_filename == trace_file and event == 'line' and frame.f_lineno == target_line:
            values = frame.f_locals
            candidates.append({k:values[k].tolist() if isinstance(values[k],np.ndarray) else values[k]
                               for k in ('score','error','preference','rotation','translation','order','signs','anchor')})
        return trace
    sys.settrace(trace)
    try:
        fitted, rotation, translation, distance, nearest = fixture.register_path(source[:,:3], contact)
    finally:
        sys.settrace(None)
    outward, blocked = fixture.accessible_direction(contact[nearest], meshes)
    args.output.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(args.output/'registration.npz', source=source, prediction=prediction,
        vertices=vertices, contact=contact, source_basis=fixture.principal_basis(points),
        contact_basis=fixture.principal_basis(contact), fitted=fitted, rotation=rotation,
        translation=translation, distance=distance, nearest=nearest, outward=outward)
    evidence = dict(python=platform.python_version(), executable=sys.executable,
        numpy=np.__version__,scipy=scipy.__version__,trimesh=trimesh.__version__,
        h5_sha256=hashlib.sha256(h5.read_bytes()).hexdigest(), obj_sha256=hashlib.sha256(obj.read_bytes()).hexdigest(),
        prediction_sha256=manifest['source_npz_sha256'], gap_mm=gap,blocked_fraction=blocked,
        candidates=sorted(candidates,key=lambda value:value['score']))
    (args.output/'registration.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    if args.prepare:
        from run_welding_sample import ExtractedSamples,prepare,sample_index
        archive=ExtractedSamples(h5.parent)
        prepare(archive,sample_index(archive)['B_PR_03_0004'],args.output/'prepared',
                prediction_dir=Path(manifest['prediction']),layout='stp',prediction_stage='final')
        from prepare_rb5_h5_trajectory import UrdfChain
        from welding_tool_geometry import CAD_TIP_LOCAL_MM,CAD_MOUNT_LOCAL_MM
        with np.load(args.output/'prepared/trajectory_solution.npz',allow_pickle=False) as solution:
            report=json.loads((args.output/'prepared/report.json').read_text(encoding='utf-8'))['workpiece']
            obj_pose=np.eye(4);obj_pose[:3,:3]=report['obj_to_world_rotation'];obj_pose[:3,3]=report['obj_to_world_translation_m']
            table_pose=np.eye(4);table_pose[:2,3]=solution['environment_table_center_xy_m'];table_pose[2,3]=float(solution['fixture_table_top_m'])-.02
            chain=UrdfChain(args.native/'rbpodo_description/robots/rb10_1300e_u.urdf')
            tcp=chain.fk(solution['joint_position_rad'][0])
            tool=tcp@solution['cad_to_robot_tcp']
            tip=(tool@np.r_[CAD_TIP_LOCAL_MM*.001,1.])[:3]
            mount=(tool@np.r_[CAD_MOUNT_LOCAL_MM*.001,1.])[:3]
            contact_world=contact*.001@obj_pose[:3,:3].T+obj_pose[:3,3]
            np.savez_compressed(args.output/'placement-evidence.npz',
                source_prediction=solution['predicted_source_xyz_m'],obj_pose=obj_pose,table_pose=table_pose,
                robot_base_pose=np.eye(4),initial_tcp_pose=tcp,initial_tool_pose=tool,
                initial_tip=tip,initial_mount=mount,contact_world=contact_world,
                gt_reference=solution['ground_truth_world_xyz_m'],fixture_outward=solution['fixture_outward'],
                source_to_scene=solution['source_to_scene'],predicted_world=solution['predicted_world_xyz_m'],
                cad_to_robot_tcp=solution['cad_to_robot_tcp'],urdf_tcp_to_weld_tcp=solution['urdf_tcp_to_weld_tcp'])
    print(json.dumps(dict(output=str(args.output), python=evidence['python'],
        candidates=len(candidates), top_score=candidates[0]['score'])))


if __name__ == '__main__':
    main()
