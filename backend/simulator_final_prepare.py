"""Native-only offline prepare bridge. No WA placement/interpolation/IK logic."""
import contextlib
import io
import json
from pathlib import Path
import sys


def bpr_tool_clearance(solution, report, root, sample_id):
    """Only this sample: exterior torch approach + 10mm virtual weld-tip stand-off.

    Original prediction, scene placement and every target XYZ remain unchanged.
    Only fixture-policy orientation, virtual TCP and native IK are derived again.
    This visual preview policy is not calibrated hardware/collision certification.
    """
    if sample_id != 'B_PR_03_0001':
        return None
    import numpy as np
    from scipy.spatial.transform import Rotation, Slerp
    from prepare_rb5_h5_trajectory import UrdfChain
    from welding_scene_layout import solve_mounted_path
    from welding_tool_geometry import CAD_MOUNT_LOCAL_MM
    solution=Path(solution)
    with np.load(solution,allow_pickle=False) as archive:
        arrays={k:archive[k] for k in archive.files}
    original=arrays['tcp_pose_xyz_mm_rpy_deg'].copy()
    tool=arrays['urdf_tcp_to_weld_tcp'].copy()
    cad=arrays['cad_to_robot_tcp']
    # B_PR CAD plate is vertical X-normal; tube front is -Y. Approach their
    # exterior bisector, 30 degrees above horizontal, instead of the open bore.
    outward=np.array([-np.sqrt(3/8),-np.sqrt(3/8),.5])
    z=np.array([0.,0.,1.]);x=np.cross(outward,z);x/=np.linalg.norm(x)
    flange=np.column_stack((x,outward,np.cross(x,outward)))
    tool[:3,3]-=np.array([0.,.010,0.])
    tip_local=np.linalg.solve(cad[:3,:3],tool[:3,3]-cad[:3,3])*1000
    poses=original.copy()
    poses[:,3:]=Rotation.from_matrix(flange@tool[:3,:3]).as_euler('xyz',degrees=True)
    raw=arrays['raw_tcp_pose_xyz_mm_rpy_deg'].copy();raw[:,3:]=poses[0,3:]
    chain=UrdfChain(Path(root)/'rbpodo_description/robots/rb10_1300e_u.urdf')
    q,position_error,orientation_error=solve_mounted_path(
        chain,poses,tool,np.rad2deg(arrays['joint_position_rad'][0]).tolist())
    tip_errors=[];rotation_errors=[];mount_errors=[]
    for i in range(len(q)-1):
        target_rotation=Slerp([0,1],Rotation.from_euler('xyz',poses[i:i+2,3:],degrees=True))
        for fraction in (0,.25,.5,.75,1):
            fk=chain.fk((1-fraction)*q[i]+fraction*q[i+1])
            tip=(fk@cad@np.r_[tip_local*.001,1])[:3]
            target=((1-fraction)*poses[i,:3]+fraction*poses[i+1,:3])*.001
            tip_errors.append(float(np.linalg.norm(tip-target)*1000))
            rotation_errors.append(float(np.rad2deg((target_rotation(fraction).inv()*Rotation.from_matrix((fk@tool)[:3,:3])).magnitude())))
            mount=(fk@cad@np.r_[CAD_MOUNT_LOCAL_MM*.001,1])[:3]
            mount_errors.append(float(np.linalg.norm(mount-fk[:3,3])*1000))
    if max(tip_errors)>1 or max(rotation_errors)>1 or max(mount_errors)>1e-6:
        raise ValueError('B_PR preview clearance IK/FK residual invalid')
    receipt=dict(sample_id=sample_id,policy='B_PR_03_0001_EXTERIOR_TORCH_VIRTUAL_TIP_V1',
        simulation_only=True,physical_robot_executable=False,source_xyz_modified=False,
        playback_xyz_modified=False,workpiece_pose_modified=False,source_to_scene_modified=False,
        gt_is_robot_target=False,orientation_source='simulator_final_policy',vla_orientation=False,
        exterior_direction=outward.tolist(),torch_standoff_mm=10,weld_tip_local_mm=tip_local.tolist(),
        source_point_count=len(raw),playback_point_count=len(poses),
        note='Preview-only exterior torch posture; original model XYZ remain the virtual weld target. No physical collision certification.')
    # Preserve the native uncorrected solution separately in this new owned package.
    with (solution.parent/'uncorrected_trajectory_solution.npz').open('xb') as stream:
        stream.write(solution.read_bytes())
    arrays.update(raw_tcp_pose_xyz_mm_rpy_deg=raw,tcp_pose_xyz_mm_rpy_deg=poses,
        joint_position_rad=q,urdf_tcp_to_weld_tcp=tool,weld_tip_local_mm=tip_local,
        position_error_mm=position_error,orientation_error_deg=orientation_error)
    assert np.array_equal(arrays['tcp_pose_xyz_mm_rpy_deg'][:,:3],original[:,:3])
    np.savez_compressed(solution,**arrays)
    report.update(position_error_mm_max=float(position_error.max()),orientation_error_deg_max=float(orientation_error.max()),
        interpolated_tip_error_mm_max=max(tip_errors),interpolated_orientation_error_deg_max=max(rotation_errors),
        cad_mount_to_flange_gap_mm_max=max(mount_errors),max_joint_step_deg=float(np.rad2deg(np.abs(np.diff(q,axis=0))).max()),
        sample_preview_correction=receipt)
    report['workpiece']['sample_preview_correction']=receipt
    (solution.parent/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (solution.parent/'sample_preview_correction.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    return receipt


def main(options):
    import numpy as np
    from backend.services.simulator_final_contract import require_native_contract
    from backend.simulator2_prepare import validate_playback
    project=Path(__file__).resolve().parents[1]
    root,h5,obj,output=(Path(options[key]).resolve() for key in ('root','h5','obj','output'))
    if (options.get('backend')!='dataset_final' or options.get('layout')!='stp' or options['kind']!='robot'
            or not options.get('prediction') or not output.is_relative_to(project/'.cache')
            or output.is_relative_to(root) or h5.stem!=options['sample_id'] or obj.stem!=h5.stem):
        raise ValueError('Invalid fixed final native manifest')
    require_native_contract(root)
    sys.path.insert(0,str(root))
    from run_welding_sample import ExtractedSamples,prepare,sample_index
    teaching=next(p for p in h5.parents if p.name=='로봇티칭데이터')
    if teaching.parent/'모델링 데이터'/h5.relative_to(teaching).with_suffix('.obj')!=obj:
        raise ValueError('Native exact OBJ mapping differs')
    archive=ExtractedSamples(h5.parent);index=sample_index(archive)
    if set(index)!={options['sample_id']}:raise ValueError('Expected one exact native sample')
    solution=prepare(archive,index[options['sample_id']],output,
        prediction_dir=Path(options['prediction']),layout='stp',prediction_stage='final')
    report=json.loads((output/'report.json').read_text(encoding='utf-8'))
    correction=bpr_tool_clearance(solution,report,root,options['sample_id'])
    with np.load(solution,allow_pickle=False) as arrays:
        check=validate_playback(arrays['raw_tcp_pose_xyz_mm_rpy_deg'],arrays['tcp_pose_xyz_mm_rpy_deg'],arrays['playback_waypoint_parameter'])
        check['frame']='simulator_final_scene'
        matrix=arrays['source_to_scene'].tolist()
    return dict(ok=True,sample_id=options['sample_id'],kind='robot',validation=check,
        source_to_scene=matrix,orientation_source='simulator_final_policy',vla_orientation=False,
        prediction_input=True,robot_ready=True,native_layout='stp',native_flags=['--layout','stp'],cad_source='sample_obj',
        environment=report['workpiece']['environment'],fk_residual_mm_max=report['interpolated_tip_error_mm_max'],
        orientation_residual_deg_max=report['interpolated_orientation_error_deg_max'],
        gt_h5_frame_error_mm_max=report['prediction']['gt_h5_frame_error_mm_max'],
        **({'sample_preview_correction':correction} if correction else {}))


if __name__=='__main__':
    sys.dont_write_bytecode=True
    project=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(project));sys.path.insert(0,str(project/'.cache/simulator2/python-deps'))
    options=json.loads(sys.stdin.read())
    try:
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):result=main(options)
    except Exception as exc:
        result=dict(ok=False,code='SIMULATOR_FINAL_SCENE_BUILD_FAIL',exception_class=type(exc).__name__)
    print(json.dumps(result,allow_nan=False))
