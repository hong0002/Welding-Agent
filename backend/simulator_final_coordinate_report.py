"""Compare existing preparation evidence only; no model or SimulationApp calls."""
import json
from pathlib import Path
import sys
import numpy as np


def angle(a,b):
    r=a@b.T
    sine=np.linalg.norm([r[2,1]-r[1,2],r[0,2]-r[2,0],r[1,0]-r[0,1]])/2
    return float(np.degrees(np.arctan2(sine,(np.trace(r)-1)/2)))


def placement(folder,native):
    from prepare_rb5_h5_trajectory import UrdfChain
    from welding_tool_geometry import CAD_TIP_LOCAL_MM,CAD_MOUNT_LOCAL_MM
    with np.load(folder/'prepared/trajectory_solution.npz',allow_pickle=False) as solution,np.load(folder/'registration.npz',allow_pickle=False) as registration:
        report=json.loads((folder/'prepared/report.json').read_text(encoding='utf-8'))['workpiece']
        obj=np.eye(4);obj[:3,:3]=report['obj_to_world_rotation'];obj[:3,3]=report['obj_to_world_translation_m']
        table=np.eye(4);table[:2,3]=solution['environment_table_center_xy_m'];table[2,3]=float(solution['fixture_table_top_m'])-.02
        tcp=UrdfChain(native/'rbpodo_description/robots/rb10_1300e_u.urdf').fk(solution['joint_position_rad'][0])
        tool=tcp@solution['cad_to_robot_tcp']
        return dict(source_prediction=solution['predicted_source_xyz_m'].copy(),obj_pose=obj,table_pose=table,
            robot_base_pose=np.eye(4),initial_tcp_pose=tcp,initial_tool_pose=tool,
            initial_tip=(tool@np.r_[CAD_TIP_LOCAL_MM*.001,1.])[:3],
            initial_mount=(tool@np.r_[CAD_MOUNT_LOCAL_MM*.001,1.])[:3],
            contact_world=registration['contact']*.001@obj[:3,:3].T+obj[:3,3],
            gt_reference=solution['ground_truth_world_xyz_m'].copy(),fixture_outward=solution['fixture_outward'].copy(),
            source_to_scene=solution['source_to_scene'].copy(),predicted_world=solution['predicted_world_xyz_m'].copy(),
            cad_to_robot_tcp=solution['cad_to_robot_tcp'].copy(),urdf_tcp_to_weld_tcp=solution['urdf_tcp_to_weld_tcp'].copy())


def difference(a,b):
    result={key:dict(max_abs=float(np.abs(a[key]-b[key]).max()),shape=list(a[key].shape)) for key in a}
    for key in ('obj_pose','table_pose','robot_base_pose','initial_tcp_pose','initial_tool_pose','source_to_scene','cad_to_robot_tcp','urdf_tcp_to_weld_tcp'):
        result[key].update(rotation_deg=angle(a[key][:3,:3],b[key][:3,:3]),translation_m=float(np.linalg.norm(a[key][:3,3]-b[key][:3,3])))
    result['predicted_world']['max_point_difference_mm']=float(np.linalg.norm(a['predicted_world']-b['predicted_world'],axis=1).max()*1000)
    return result


def main():
    project=Path(__file__).resolve().parents[1];native=project.parent/'simulator_final'
    sys.path.insert(0,str(native));root=project/'.cache/simulator-final-coordinate'
    before=[placement(root/'before'/env,native) for env in ('py312','isaac')]
    after=[{k:v.copy() for k,v in np.load(root/'final'/env/'placement-evidence.npz',allow_pickle=False).items()} for env in ('py312','isaac')]
    result=dict(sample_id='B_PR_03_0004',coordinate_alignment_fixed=True,
        before=difference(*before),after=difference(*after),original_py312_reference=difference(before[0],after[0]),
        numeric_evidence={stage:{env:{k:v.tolist() for k,v in value.items() if v.shape in ((4,4),(3,))}
            for env,value in zip(('py312','isaac'),values)} for stage,values in (('before',before),('after',after))},
        robot_base_policy='Native URDF fixed link0, identity; no runtime root transform',
        orientation_source='simulator_final_policy',vla_orientation=False,model_calls=0,
        note='GT participates in original native fixture registration/reference only. Playback targets are original prediction transformed by the same rigid source_to_scene; no GT substitution.')
    (root/'comparison.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({stage:dict(rotation_deg=result[stage]['source_to_scene']['rotation_deg'],
        translation_m=result[stage]['source_to_scene']['translation_m'],
        predicted_max_difference_mm=result[stage]['predicted_world']['max_point_difference_mm'])
        for stage in ('before','after','original_py312_reference')}))


if __name__=='__main__':main()
