"""Place an undeformed CAD workpiece upright and rigidly relocate source poses.

This is an explicit simulation fixture, not recovered camera-to-robot calibration.
"""
import numpy as np
from scipy.spatial.transform import Rotation
from welding_workpiece import load_obj_mesh, infer_plate_round_seam, _obj_connected_components, _pca_component

LEGACY_FIXTURES = ('L_PR_', 'T_PP_', 'T_PR_')
SUPPORTED_FIXTURES = tuple(f'{joint}_{material}_' for joint in ('B', 'C', 'E', 'L', 'T')
                           for material in ('PP', 'PR', 'PS', 'RR', 'RS', 'SS'))


def fixture_supported(sample):
    return sample.startswith(SUPPORTED_FIXTURES)


def tee_plate_round(vertices, counts, indices):
    """Put the plate below the pipe, then locate the accessible circular joint."""
    parts=[_pca_component(vertices,c) for c in _obj_connected_components(len(vertices),counts,indices)]
    if len(parts)!=2:
        raise ValueError('T_PR expects one pipe and one plate component')
    plate=min(parts,key=lambda p: np.min(p['extents'])/np.max(p['extents']))
    pipe=next(p for p in parts if p is not plate)
    normal=plate['axes'][:,np.argmin(plate['extents'])].copy()
    if np.dot(normal,pipe['center']-plate['center'])<0:normal*=-1
    from welding_workpiece import rotation_between
    rotation=rotation_between(normal,[0.,0.,1.])
    upright=vertices@rotation.T
    plate_points=upright[plate['indices']];pipe_points=upright[pipe['indices']]
    center=(pipe_points.min(0)+pipe_points.max(0))/2
    center[2]=plate_points[:,2].max()
    radius=float(np.max(np.linalg.norm(pipe_points[:,:2]-center[:2],axis=1)))
    anchor=center+np.array([0.,-radius,0.])
    return upright,rotation,anchor,center,radius


def frame(seam, outward):
    y = np.asarray(seam,dtype=float).copy(); y /= np.linalg.norm(y)
    z = np.asarray(outward,dtype=float).copy(); z -= y*np.dot(y,z)
    if np.linalg.norm(z)<1e-6:
        raise ValueError('Cannot build work frame: approach is parallel to seam')
    z /= np.linalg.norm(z)
    return np.column_stack((np.cross(y,z),y,z))


def object_seam(vertices,counts,indices,sample):
    if sample.startswith('L_PR_'):
        geometry=infer_plate_round_seam(vertices,counts,indices)
        return geometry['seam_center_mm'],geometry['seam_axis'],geometry['plate_normal']
    if sample.startswith('T_PP_'):
        components=[_pca_component(vertices,c) for c in _obj_connected_components(len(vertices),counts,indices)]
        if len(components)!=2:
            raise ValueError('T_PP fixture expects two plate components')
        base=min(components,key=lambda c: np.ptp(c['points'][:,2]))
        vertical=next(c for c in components if c is not base)
        normal=vertical['axes'][:,np.argmin(vertical['extents'])].copy()
        # Select the accessible side facing the robot (negative X when possible).
        if normal[0]>0: normal*=-1
        seam=np.cross(normal,[0.,0.,1.]);seam/=np.linalg.norm(seam)
        anchor=vertical['center'].copy()
        anchor[2]=base['points'][:,2].max()
        anchor+=normal*(np.min(vertical['extents'])/2)
        return anchor,seam,normal+np.array([0.,0.,1.])
    raise ValueError(f'{sample}: fixture geometry currently supports L_PR, T_PP, and T_PR. '
                     'Refusing to invent a contact seam for this object type.')


def build_scene(obj_path,sample,source_poses):
    v,c,i=load_obj_mesh(obj_path)
    if not np.isfinite(v).all() or min(i)<0 or max(i)>=len(v):
        raise ValueError('Invalid OBJ')
    if not fixture_supported(sample):
        raise ValueError(f'{sample}: unknown joint/material family')
    if not sample.startswith(LEGACY_FIXTURES):
        from welding_contact_fixture import build_contact_scene
        poses, arrays, report = build_contact_scene(v,c,i,sample,source_poses)
        report['source_obj'] = str(obj_path)
        return poses, arrays, report
    cad_rotation=np.eye(3)
    circle=None
    if sample.startswith('T_PR_'):
        v,cad_rotation,anchor,circle_center,circle_radius=tee_plate_round(v,c,i)
        circle=(circle_center,circle_radius)
        seam,outward=np.array([1.,0.,0.]),np.array([0.,0.,1.])
    else:
        anchor,seam,outward=object_seam(v,c,i,sample)
    # Preserve the CAD axes: the source photos show L_PR standing on its end.
    target_basis=frame(seam,outward)
    source_rotations=Rotation.from_euler('xyz',source_poses[:,3:],degrees=True).as_matrix()
    source_direction=source_poses[-1,:3]-source_poses[0,:3]
    if circle is not None:
        bend=source_poses[:,:3].mean(0)-(source_poses[0,:3]+source_poses[-1,:3])/2
        plane_normal=np.cross(bend,source_direction)
        if np.linalg.norm(plane_normal)<1e-8:
            _,_,basis=np.linalg.svd(source_poses[:,:3]-source_poses[:,:3].mean(0))
            plane_normal=basis[-1]
        source_basis=frame(source_direction,plane_normal)
    else:
        source_basis=frame(source_direction,source_rotations[:,:,1].mean(axis=0))
    rotation=target_basis @ source_basis.T
    fixture_center=np.array([.85,.15,.50])
    translation=fixture_center-rotation@(source_poses[:,:3].mean(axis=0)*.001)
    poses=source_poses.copy()
    poses[:,:3]=((rotation@(source_poses[:,:3]*.001).T).T+translation)*1000
    poses[:,3:]=Rotation.from_matrix(rotation@source_rotations).as_euler('xyz',degrees=True)
    object_translation=fixture_center-anchor*.001
    world=v*.001+object_translation
    rigid=np.eye(4);rigid[:3,:3]=rotation;rigid[:3,3]=translation
    # Full pose transform applied uniformly: no per-waypoint orientation relaxation.
    arrays=dict(workpiece_vertices_world_m=world,
                workpiece_face_counts=np.asarray(c,dtype=np.int32),
                workpiece_face_indices=np.asarray(i,dtype=np.int32),
                source_to_scene=rigid,source_tcp_pose_xyz_mm_rpy_deg=source_poses,
                fixture_table_top_m=np.asarray(world[:,2].min()))
    report=dict(source_obj=str(obj_path),placement='upright CAD simulation fixture',
                original_cad_axes_preserved=bool(np.allclose(cad_rotation,np.eye(3))),object_deformed=False,
                obj_to_world_rotation=cad_rotation.tolist(),obj_to_world_translation_m=object_translation.tolist(),
                source_to_scene=rigid.tolist(),
                note='Path and all tool orientations relocated by one rigid transform. Not original robot-world calibration.')
    if circle is not None:
        center,radius=circle
        world_center=center*.001+object_translation
        radial=np.linalg.norm(poses[:,:2]*.001-world_center[:2],axis=1)
        deviation=np.sqrt((radial-radius*.001)**2+(poses[:,2]*.001-world_center[2])**2)*1000
        report.update(placement='T_PR upright plate/pipe circular-joint preview',
                      gt_to_nominal_joint_mm_max=float(deviation.max()),
                      gt_to_nominal_joint_mm_mean=float(deviation.mean()),
                      note='Upright CAD; GT arc plane placed at pipe/plate joint without scaling or projecting. '
                           'Source arc radius may differ from CAD; residual is reported. Not recovered calibration.')
        arrays['fixture_outward']=np.array([0.,-1.,1.])/np.sqrt(2)
        arrays['camera_eye_offset_m']=np.array([.8,-1.2,.65])
        print(f'[FIXTURE] {sample}: plate below pipe; nominal joint deviation max={deviation.max():.3f} mm',flush=True)
    else:
        print(f'[FIXTURE] {sample}: original CAD axes; path and poses rigidly relocated',flush=True)
    return poses,arrays,report


def densify_poses(poses, max_step_mm=5., max_rotation_deg=3.):
    """Subdivide the same piecewise Cartesian path; retain every original corner."""
    from scipy.spatial.transform import Slerp
    poses = np.asarray(poses, dtype=float)
    result, parameters = [], []
    for index, (a, b) in enumerate(zip(poses[:-1], poses[1:])):
        rotations = Rotation.from_euler('xyz', np.stack((a[3:], b[3:])), degrees=True)
        angle = np.rad2deg((rotations[0].inv()*rotations[1]).magnitude())
        count = max(1, int(np.ceil(np.linalg.norm(b[:3]-a[:3])/max_step_mm)),
                    int(np.ceil(angle/max_rotation_deg)))
        fractions = np.arange(count)/count
        positions = a[:3] + fractions[:, None]*(b[:3]-a[:3])
        orientations = Slerp([0., 1.], rotations)(fractions).as_euler('xyz', degrees=True)
        result.extend(np.column_stack((positions, orientations)))
        parameters.extend(index+fractions)
    result.append(poses[-1]); parameters.append(len(poses)-1)
    return np.asarray(result), np.asarray(parameters)


def solve_mounted_path(chain,poses,tool,teaching_seed):
    from prepare_rb5_h5_trajectory import solve_path
    seeds=[teaching_seed,[0,-30,100,-60,-90,0],[0,30,-90,30,90,0],[0,0,90,-90,90,0],
           [0,-60,120,-60,90,0],[45,0,90,0,90,90],[-45,0,90,0,-90,-90]]
    for seed in seeds:
        try:
            first,p,o=solve_path(chain,poses[:1],tool,seed)
        except RuntimeError:
            continue
        if p.max()<.1 and o.max()<.1:
            q,p,o=solve_path(chain,poses,tool,np.rad2deg(first[0]))
            if p.max()<1 and o.max()<1 and np.abs(np.diff(q,axis=0)).max()<np.deg2rad(30):
                return q,p,o
    raise RuntimeError('Mounted torch cannot follow this fixture with continuous full-pose IK')
