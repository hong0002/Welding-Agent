import sys as _release_sys
from pathlib import Path as _ReleasePath
_release_sys.path.insert(0, str(_ReleasePath(__file__).resolve().parents[1]))
from backend.services.project_paths import native_parent
"""Bounded static URDF/STL check, not physics or simulator playback."""
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
import h5py
import numpy as np
from scipy.spatial.transform import Rotation
from backend.offline_bpr_tool_clearance import PROJECT,AUDIT,PREVIOUS,PACKAGE,read,save,sha
from backend.services.offline_mesh_clearance import TriangleSurface,surface_clearance


def main():
    simulator=native_parent(PROJECT)/'simulator'
    urdf=simulator/'rbpodo_description/robots/rb10_1300e_u.urdf'
    tree=ET.parse(urdf).getroot()
    paths=[urdf]+[simulator/mesh.attrib['filename'].replace('package://','')
        for mesh in tree.findall('./link/collision/geometry/mesh')]
    before={str(p):sha(p) for p in paths}
    sys.path.insert(0,str(simulator))
    from prepare_rb5_h5_trajectory import UrdfChain,solve_path,JOINT_NAMES,matrix_from_xyz_rpy
    from welding_tool_geometry import mounted_cad_transform,mounted_tip_transform
    chain=UrdfChain(urdf);cad=mounted_cad_transform();tool=mounted_tip_transform()
    previous,usd,package=read(PREVIOUS),read(AUDIT/'usd_geometry.json'),read(PACKAGE)
    with h5py.File(package['h5'],'r') as handle:poses=np.asarray(handle['trajectory'],dtype=float)
    # Existing reachable -X diagnostic candidate; no alternate IK seed search.
    c=previous['candidates'][0]
    assert c['outward_sign']==-1
    transform=np.array(c['source_to_scene']);r=transform[:3,:3]
    world_r=r@Rotation.from_euler('xyz',poses[:,3:],degrees=True).as_matrix()
    y=np.array(c['outward']);z=np.array([0.,0.,1.]);x=np.cross(y,z);x/=np.linalg.norm(x);z=np.cross(x,y)
    tool[:3,:3]=np.column_stack((x,y,z)).T@Rotation.from_matrix(world_r).mean().as_matrix()
    initial=np.r_[(r@(poses[0,:3]*.001)+transform[:3,3])*1000,
                  Rotation.from_matrix(world_r[0]).as_euler('xyz',degrees=True)][None]
    q,pos_error,rot_error=solve_path(chain,initial,tool,[0,-30,100,-60,-90,0])
    assert pos_error.max()<1 and rot_error.max()<1
    flange=chain.fk(q[0]);mounted=flange@cad
    mesh=usd['meshes'][0];tv=np.array(mesh['asset_points']);tf=np.array(mesh['face_indices']).reshape(-1,3)
    tool_world=tv*.001@mounted[:3,:3].T+mounted[:3,3]
    tool_surface=TriangleSurface(tool_world,tf)
    links={'link0':np.eye(4)}
    for index,name in enumerate((*JOINT_NAMES,'tcp_joint')):
        joint=next(j for j in tree.findall('joint') if j.attrib['name']==name)
        origin=joint.find('origin')
        origin_matrix=matrix_from_xyz_rpy(np.fromstring(origin.attrib.get('xyz','0 0 0'),sep=' '),
            np.fromstring(origin.attrib.get('rpy','0 0 0'),sep=' '))
        rotation=np.eye(4)
        if joint.attrib['type']!='fixed':
            axis=np.fromstring(joint.find('axis').attrib['xyz'],sep=' ')
            rotation[:3,:3]=Rotation.from_rotvec(axis*q[0,index]).as_matrix()
        links[joint.find('child').attrib['link']]=links[joint.find('parent').attrib['link']]@origin_matrix@rotation
    assert np.max(abs(links['tcp']-flange))<1e-12
    result=dict(sample_id='B_PR_03_0001',candidate=-1,pose='initial_GT',
        robot_geometry_source='native URDF collision STL meshes, static FK, identity base',
        robot_visual_mesh_checked=False,actual_imported_stage_checked=False,
        kinematic_solver='one initial pose, native solve_path and native prediction seed; no physics',
        position_error_mm=float(pos_error[0]),orientation_error_deg=float(rot_error[0]),
        orientation_source='simulator_fixture_policy',runtime_approved=False,links=[])
    for link in tree.findall('link'):
        for collision in link.findall('collision'):
            mesh=collision.find('geometry/mesh')
            if mesh is None:continue
            path=simulator/mesh.attrib['filename'].replace('package://','')
            raw=path.read_bytes();count=int.from_bytes(raw[80:84],'little')
            assert len(raw)==84+50*count
            dtype=np.dtype([('normal','<f4',(3,)),('vertices','<f4',(3,3)),('attribute','<u2')])
            triangles=np.frombuffer(raw,dtype=dtype,count=count,offset=84)['vertices'].astype(float)
            scale=np.fromstring(mesh.attrib.get('scale','1 1 1'),sep=' ')
            assert scale.shape==(3,)
            matrix=links[link.attrib['name']].copy()
            origin=collision.find('origin')
            if origin is not None:
                matrix=matrix@matrix_from_xyz_rpy(np.fromstring(origin.attrib.get('xyz','0 0 0'),sep=' '),
                    np.fromstring(origin.attrib.get('rpy','0 0 0'),sep=' '))
            vertices=triangles.reshape(-1,3)*scale@matrix[:3,:3].T+matrix[:3,3]
            faces=np.arange(len(vertices)).reshape(-1,3)
            clearance=surface_clearance(tool_surface,TriangleSurface(vertices,faces))
            result['links'].append(dict(link=link.attrib['name'],path=str(path),units='URDF meters',
                triangle_count=count,attached_mount_link=link.attrib['name']=='link6',clearance=clearance))
            print(f"[STATIC ROBOT] {link.attrib['name']} tool_distance_mm={clearance['minimum_surface_distance_m']*1000:.6g} pairs={clearance['intersecting_triangle_pair_count']}",flush=True)
    after={str(p):sha(p) for p in paths}
    assert before==after
    result['source_hashes_before']=before;result['source_hashes_after']=after;result['sources_unchanged']=True
    result['scope']='initial reachable candidate only; no full robot self-collision, continuous approach/path or actual USD importer certification'
    assert not any(m=='isaacsim' or m.startswith('omni') for m in sys.modules)
    save('robot_collision.json',result)


if __name__=='__main__':main()
