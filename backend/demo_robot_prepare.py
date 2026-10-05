"""Offline native RB10 IK for a separately labelled simulation-only mapping."""
import json
import sys
from pathlib import Path


def map_runs(runs,anchor,extent_mm=60.):
    import numpy as np
    points=np.asarray([p for run in runs for p in run],dtype=float)
    if len(points)<2 or points.shape[1:]!=(3,) or not np.isfinite(points).all():raise ValueError('Finite XYZ required')
    delta=points-points[0]
    extent=float(np.max(np.linalg.norm(delta,axis=1)))
    if extent<=1e-12:raise ValueError('No source motion')
    scale=extent_mm/1000/extent
    mapped=delta*scale+np.asarray(anchor)
    ends=[];offset=0
    for run in runs:ends.append([offset,offset+len(run)]);offset+=len(run)
    return mapped,scale,ends


def main(options):
    import numpy as np
    from scipy.optimize import least_squares
    from scipy.spatial.transform import Rotation
    project=Path(__file__).resolve().parents[1]
    root=Path(options['root']).resolve();output=Path(options['output']).resolve()
    if not output.is_relative_to(project/'.cache/simulator/current-previews/packages'):raise ValueError('Owned output required')
    sys.path.insert(0,str(root))
    scene = None
    if options.get('h5'):
        from backend.services.sample_scene import prepare_demo_scene
        scene=prepare_demo_scene(h5=options['h5'],obj=options['obj'],sample=options['sample_id'],output=output,backend=options['backend'])
    from prepare_rb5_h5_trajectory import UrdfChain,JOINT_NAMES
    chain=UrdfChain(root/'rbpodo_description/robots/rb10_1300e_u.urdf')
    with np.load(options['anchor_solution'],allow_pickle=False) as data:
        seed=data['joint_position_rad'][0].copy();tool=data['urdf_tcp_to_weld_tcp'].copy()
        cad=data['cad_to_robot_tcp'].copy()
    pose=chain.fk(seed)@tool;anchor=pose[:3,3];rotation=Rotation.from_matrix(pose[:3,:3])
    source=json.loads((output/'geometry.json').read_text(encoding='utf-8'))
    q_rows=[];target_rows=[];indices=[];run_rows=[]
    # Initial 60 mm attempt, then exactly one smaller 12 mm retry. No model call.
    for attempt,extent in enumerate((60.,12.)):
        mapped,scale,bounds=map_runs(source['runs'],anchor,extent)
        q_rows=[];target_rows=[];indices=[];run_rows=[];q=seed.copy()
        for run_index,(begin,end) in enumerate(bounds):
            q=seed.copy();run_begin=len(q_rows)
            for index in range(begin,end):
                target=mapped[index]
                def residual(candidate):
                    actual=chain.fk(candidate)@tool
                    return np.r_[(actual[:3,3]-target)/.001,(rotation.inv()*Rotation.from_matrix(actual[:3,:3])).as_rotvec()/np.deg2rad(.5)]
                fit=least_squares(residual,q,bounds=(chain.lower,chain.upper),max_nfev=100,xtol=1e-10,ftol=1e-10,gtol=1e-10)
                actual=chain.fk(fit.x)@tool
                if fit.success and np.linalg.norm(actual[:3,3]-target)<.001 and np.linalg.norm(residual(fit.x)[3:])<2:
                    q=fit.x;q_rows.append(q.copy());target_rows.append(target);indices.append(index)
            run_rows.append([run_begin,len(q_rows)])
        if len(q_rows)==len(mapped):break
    if len(q_rows)<2 or float(np.abs(np.diff(q_rows,axis=0)).max())<1e-7:raise ValueError('No reachable moving sequence')
    np.savez_compressed(output/'demo_playback.npz',demo_playback_points=np.asarray(target_rows),joint_position_rad=q_rows,
        source_indices=indices,run_bounds=run_rows,cad_to_robot_tcp=cad,urdf_tcp_to_weld_tcp=tool,joint_names=np.asarray(JOINT_NAMES))
    return dict(ok=True,sample_scene=scene,anchor_tcp_m=anchor.tolist(),anchor_joints_rad=seed.tolist(),uniform_scale=scale,
        mapped_extent_mm=extent,ik_attempts=attempt+1,ik_retry_count=attempt,
        playback_point_count=len(q_rows),omitted_ik_points=len(mapped)-len(q_rows),
        orientation_source='simulator_policy: reused successful RB10 pose',vla_orientation=False,
        max_joint_delta_rad=float(np.abs(np.diff(q_rows,axis=0)).max()))


if __name__=='__main__':
    sys.dont_write_bytecode=True
    project=Path(__file__).resolve().parents[1];sys.path.insert(0,str(project));sys.path.insert(0,str(project/'.cache/simulator2/python-deps'))
    try:result=main(json.loads(sys.stdin.read()))
    except Exception as exc:result=dict(ok=False,code='ROBOT_DEMO_IK_UNAVAILABLE',exception_class=type(exc).__name__)
    print(json.dumps(result,allow_nan=False))
