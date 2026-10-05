"""Native-only offline prepare bridge. No WA placement/interpolation/IK logic."""
import contextlib
import io
import json
from pathlib import Path
import sys


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
    with np.load(solution,allow_pickle=False) as arrays:
        check=validate_playback(arrays['raw_tcp_pose_xyz_mm_rpy_deg'],arrays['tcp_pose_xyz_mm_rpy_deg'],arrays['playback_waypoint_parameter'])
        check['frame']='simulator_final_scene'
        matrix=arrays['source_to_scene'].tolist()
    return dict(ok=True,sample_id=options['sample_id'],kind='robot',validation=check,
        source_to_scene=matrix,orientation_source='simulator_final_policy',vla_orientation=False,
        prediction_input=True,robot_ready=True,native_layout='stp',native_flags=['--layout','stp'],cad_source='sample_obj',
        environment=report['workpiece']['environment'],fk_residual_mm_max=report['interpolated_tip_error_mm_max'],
        orientation_residual_deg_max=report['interpolated_orientation_error_deg_max'],
        gt_h5_frame_error_mm_max=report['prediction']['gt_h5_frame_error_mm_max'])


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
