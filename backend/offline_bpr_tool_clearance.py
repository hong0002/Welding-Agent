"""Fixed one-sample offline audit; no runtime registry, inference or Isaac app.

The only Isaac operation is a separate isolated USD-reader invocation. This
module consumes its saved triangle data using the native NumPy/SciPy Python.
"""
import hashlib
import json
from pathlib import Path
import sys
import time
import h5py
import numpy as np
from scipy.spatial.transform import Rotation
from backend.services.offline_mesh_clearance import (
    TriangleSurface, surface_clearance, triangle_pairs, solid_angle_inside,
)

PROJECT=Path(__file__).resolve().parents[1]
AUDIT=PROJECT/'.cache/bpr-tool-clearance/a74cb77c-7d4e-4617-b20d-57a43fcb89cf'
PREVIOUS=PROJECT/'.cache/bpr-geometry-audit/0efd49b0-a360-466e-b7f1-2fe5cdee0d2e/diagnostics.json'
PACKAGE=PROJECT/'.cache/simulator/prediction-packages/f72c8af8-d291-4070-a6b5-d3ccf05170a9/package.json'


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))
def save(name,value):
    with (AUDIT/name).open('x',encoding='utf-8') as stream:
        json.dump(value,stream,indent=2,allow_nan=False)


def box(low,high):
    v=np.array([[x,y,z] for x in (low[0],high[0]) for y in (low[1],high[1]) for z in (low[2],high[2])])
    f=np.array([[0,2,3],[0,3,1],[4,5,7],[4,7,6],[0,1,5],[0,5,4],
                [2,6,7],[2,7,3],[0,4,6],[0,6,2],[1,3,7],[1,7,5]])
    return TriangleSurface(v,f)


def topology(faces):
    edges=np.concatenate([faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]])
    canonical=np.sort(edges,axis=1)
    _,counts=np.unique(canonical,axis=0,return_counts=True)
    # Equal numbers of both directed uses establishes consistent orientation.
    direction=np.where(edges[:,0]<edges[:,1],1,-1)
    _,inverse=np.unique(canonical,axis=0,return_inverse=True)
    signed=np.bincount(inverse,weights=direction)
    return dict(boundary_edges=int(sum(counts==1)),nonmanifold_edges=int(sum(counts>2)),
                inconsistent_edges=int(sum(signed!=0)),closed=bool(np.all(counts==2)&np.all(signed==0)))


def main():
    started=time.monotonic()
    package,previous,usd=read(PACKAGE),read(PREVIOUS),read(AUDIT/'usd_geometry.json')
    source=Path(usd['source'])
    h5,obj=Path(package['h5']),Path(package['obj'])
    npz=Path(package['prediction_root'])/package['sample_id']/'trajectory.npz'
    paths=[PACKAGE,PREVIOUS,source,h5,obj,npz]
    paths += [PROJECT.parent/'simulator'/name for name in package['provenance']['simulator_files']]
    before={str(p):sha(p) for p in paths}
    assert package['sample_id']=='B_PR_03_0001'
    assert before[str(PACKAGE)]==previous['package_sha256_before']
    assert sha(h5)==package['provenance']['h5_sha256']
    assert sha(obj)==package['provenance']['obj_sha256']
    assert sha(npz)==package['provenance']['source_files']['trajectory.npz']
    assert all(sha(PROJECT.parent/'simulator'/name)==digest
               for name,digest in package['provenance']['simulator_files'].items())
    assert sha(source)==usd['source_sha256_before']==usd['source_sha256_after']
    sys.path.insert(0,str(PROJECT.parent/'simulator'))
    # These two audited source modules are pure NumPy geometry; their script
    # mains and all simulator/omni modules are excluded.
    from welding_workpiece import load_obj_mesh, _obj_connected_components
    from welding_tool_geometry import mounted_cad_transform, mounted_tip_transform, CAD_TIP_LOCAL_MM, CAD_MOUNT_LOCAL_MM
    vertices,counts,indices=load_obj_mesh(obj)
    assert np.all(np.asarray(counts)==3)
    faces=np.array(indices).reshape(-1,3)
    components=_obj_connected_components(len(vertices),counts,indices)
    offset=np.array(previous['object_placement_candidate_only']['object_translation_m'])
    workpiece=np.array(vertices)*.001+offset
    work_surface=TriangleSurface(workpiece,faces)
    component_surfaces=[]
    for ids in components:
        selected=np.all(np.isin(faces,ids),axis=1)
        fs=faces[selected]
        comp=TriangleSurface(workpiece,fs)
        component_surfaces.append((comp,topology(fs)))
    assert len(usd['meshes'])==1
    mesh=usd['meshes'][0]
    assert set(mesh['face_counts'])=={3} and not mesh['holes']
    assert mesh['subdivision']=='none' and not mesh['points_time_samples']
    tv=np.array(mesh['asset_points']);tf=np.array(mesh['face_indices']).reshape(-1,3)
    assert all(np.allclose(h['local_to_asset_row_matrix'],np.eye(4),atol=0,rtol=0) for h in usd['hierarchy'])
    cad,mount_tip=mounted_cad_transform(),mounted_tip_transform()
    # Match the external add_torch_at_tcp Geometry scale: exactly once, .001.
    mesh_flange=tv*.001@cad[:3,:3].T+cad[:3,3]
    tip_local=np.array(CAD_TIP_LOCAL_MM)
    d,cp,ct=triangle_pairs(np.broadcast_to(tip_local,(len(tf),3,3)),tv[tf])
    closest=int(np.argmin(d))
    _,eigen=np.linalg.eigh(np.cov(tv.T));principal=eigen[:,-1]
    if principal[2]<0: principal=-principal
    # Distal PCA is geometry-only; not used to alter the existing fixture pose.
    distal=tv[tv[:,2]>400]
    _,axes=np.linalg.eigh(np.cov(distal.T));nozzle=axes[:,-1]
    if nozzle[2]<0:nozzle=-nozzle
    asset_geometry=dict(bounds_mm=[tv.min(0).tolist(),tv.max(0).tolist()],
        vertices=len(tv),triangles=len(tf),asset_origin_mm=[0,0,0],
        principal_axis_cad=principal.tolist(),distal_region='CAD Z > 400 mm, PCA diagnostic only',
        distal_principal_axis_cad=nozzle.tolist(),cad_mount_mm=CAD_MOUNT_LOCAL_MM.tolist(),
        cad_tip_mm=tip_local.tolist(),tip_definition='existing welding_tool_geometry.CAD_TIP_LOCAL_MM; no USD tip marker',
        tip_distance_to_actual_surface_mm=float(np.sqrt(d[closest])),
        tip_closest_surface_mm=ct[closest].tolist(),tip_surface_triangle=closest,
        tip_is_outermost_z=False,maximum_mesh_z_mm=float(tv[:,2].max()),
        mount_rear_face_bounds_mm=[tv[abs(tv[:,2]-tv[:,2].min())<1e-7].min(0).tolist(),
                                   tv[abs(tv[:,2]-tv[:,2].min())<1e-7].max(0).tolist()],
        mounted_cad_transform=cad.tolist(),tip_translation_in_flange_m=mount_tip[:3,3].tolist())
    with h5py.File(h5,'r') as handle: poses=np.asarray(handle['trajectory'],dtype=float)
    with np.load(npz,allow_pickle=False) as loaded:
        gt,pred=loaded['ground_truth_path_m'].astype(float),loaded['predicted_path_m'].astype(float)
    assert gt.shape==pred.shape==(9,3)
    table_top=float(workpiece[:,2].min());center=workpiece.mean(0)
    table=box(center+[-.15,-.15,table_top-.04-center[2]],center+[.15,.15,table_top-center[2]])
    legs=[]
    for dx,dy in ((-.12,-.12),(-.12,.12),(.12,-.12),(.12,.12)):
        leg_center=np.array([center[0]+dx,center[1]+dy,(table_top-.04)/2])
        leg_half=np.array([.0125,.0125,(table_top-.04)/2])
        legs.append(box(leg_center-leg_half,leg_center+leg_half))
    ground=box(np.array([-1.5,-1.5,-.05]),np.array([1.5,1.5,0.]))
    report=dict(audit_id=AUDIT.name,sample_id=package['sample_id'],package_id=package['package_id'],
        reader_file='usd_geometry.json',asset_geometry=asset_geometry,orientation_source='simulator_fixture_policy',
        runtime_registry_connected=False,runtime_approved=False,physical_clearance_threshold_m=None,
        workpiece_bounds_m=[workpiece.min(0).tolist(),workpiece.max(0).tolist()],
        component_topology=[t for _,t in component_surfaces],
        table_bounds_m=[table.nodes[0].low.tolist(),table.nodes[0].high.tolist()],
        table_source='run_rb10_trajectory_with_ATU01035.py:494-511 (source cubes, no stage execution)',
        ade_mm=package['ade_mm'],fde_mm=package['fde_mm'],candidates=[])
    for candidate in previous['candidates']:
        transform=np.array(candidate['source_to_scene'])
        r=transform[:3,:3];t=transform[:3,3]
        flange_r=np.array(candidate['fixed_tool_diagnostic']['initial_flange_rotation'])
        outward=np.array(candidate['outward'])
        scene_r=r@Rotation.from_euler('xyz',poses[:,3:],degrees=True).as_matrix()
        y=outward;z=np.array([0.,0.,1.]);x=np.cross(y,z);x/=np.linalg.norm(x);z=np.cross(x,y)
        reference=np.column_stack((x,y,z))
        tool_r=reference.T@Rotation.from_matrix(scene_r).mean().as_matrix()
        reproduced=scene_r[0]@tool_r.T
        assert np.max(abs(reproduced-flange_r))<1e-12
        gt_world=gt@r.T+t;pred_world=pred@r.T+t
        full_gt=poses[:,:3]*.001@r.T+t
        body_relative=(mesh_flange-mount_tip[:3,3])@flange_r.T
        assert np.allclose(full_gt[0]-flange_r@mount_tip[:3,3],candidate['fixed_tool_diagnostic']['initial_flange_xyz_m'],atol=1e-12,rtol=0)
        result=dict(outward_sign=candidate['outward_sign'],source_to_scene=transform.tolist(),
            object_translation_m=offset.tolist(),flange_rotation=flange_r.tolist(),
            orientation_source='simulator_fixture_policy',orientation_policy='fixed first transformed GT orientation with native mean fixture tool reference',
            world_cad_mount_axis=(flange_r@cad[:3,:3]@np.array([0.,0.,1.])).tolist(),
            world_distal_nozzle_axis=(flange_r@cad[:3,:3]@nozzle).tolist(),
            prediction_distance_invariance_error_mm=float(np.max(abs(np.linalg.norm(pred_world-gt_world,axis=1)-np.linalg.norm(pred-gt,axis=1)))*1000),
            gt_path=[],prediction_path=[],approach_samples=[])
        def evaluate(point,label,fixture=False,containment=False):
            body=tv*.001@cad[:3,:3].T+cad[:3,3]
            world=(body-mount_tip[:3,3])@flange_r.T+point
            surface=TriangleSurface(world,tf)
            clearance=surface_clearance(surface,work_surface)
            data=dict(label=label,clearance=clearance,mesh_world_bounds_m=[world.min(0).tolist(),world.max(0).tolist()])
            if fixture:
                data['table']=surface_clearance(surface,table)
                data['legs']=[surface_clearance(surface,leg) for leg in legs]
                data['ground']=surface_clearance(surface,ground)
            if containment:
                inside=[]
                for index,(component,topo) in enumerate(component_surfaces):
                    low,high=component.nodes[0].low,component.nodes[0].high
                    ids=np.flatnonzero(np.all((world>low)&(world<high),axis=1))
                    winding=solid_angle_inside(world[ids],component.triangles)
                    selected=ids[abs(winding)>.5]
                    records=[]
                    for vid in selected:
                        d,a,b=triangle_pairs(np.broadcast_to(world[vid],(len(component.triangles),3,3)),component.triangles)
                        nearest=int(np.argmin(d))
                        records.append(dict(tool_vertex=int(vid),depth_m=float(np.sqrt(d[nearest])),
                            point_m=world[vid].tolist(),closest_workpiece_m=b[nearest].tolist()))
                    inside.append(dict(component=index,closed=topo['closed'],inside_vertex_count=len(selected),
                        deepest_vertex=max(records,key=lambda q:q['depth_m']) if records else None))
                data['solid_containment']=inside
            print(f"[OFFLINE] sign={candidate['outward_sign']} {label} distance_mm={clearance['minimum_surface_distance_m']*1000:.6g} pairs={clearance['intersecting_triangle_pair_count']} wall_s={time.monotonic()-started:.1f}",flush=True)
            return data
        result['initial_gt_pose']=evaluate(full_gt[0],'initial_gt',fixture=True,containment=True)
        # No native pre-approach length exists. These offsets probe the already
        # declared candidate outward direction only; they are not a new policy.
        for distance in (.05,.02,.01,.005,.002,.001,0.):
            data=evaluate(full_gt[0]+outward*distance,f'approach_offset_{distance*1000:g}mm')
            data['diagnostic_offset_m']=distance
            result['approach_samples'].append(data)
        for i,point in enumerate(gt_world):result['gt_path'].append(evaluate(point,f'GT_{i}'))
        for i,point in enumerate(pred_world):result['prediction_path'].append(evaluate(point,f'prediction_{i}',fixture=i in (0,8)))
        result['sampled_path_only']=True
        result['approach_is_native_policy']=False
        report['candidates'].append(result)
        save(f"candidate_{candidate['outward_sign']}.json",result)
    after={str(p):sha(p) for p in paths}
    report['source_hashes_before']=before;report['source_hashes_after']=after
    report['all_sources_unchanged']=before==after
    report['package_fixture_ready']=read(PACKAGE)['preflight']['fixture_ready']
    report['elapsed_s']=time.monotonic()-started
    report['forbidden_modules_loaded']=[m for m in sys.modules if m=='isaacsim' or m.startswith('omni')]
    assert before==after and report['package_fixture_ready'] is False and not report['forbidden_modules_loaded']
    save('clearance.json',report)
    print('[OFFLINE] completed, registry remains blocked',flush=True)


if __name__=='__main__': main()
