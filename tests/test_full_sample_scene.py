"""Shared Strict/Demo scene; fake native and USD, no Isaac or model invocation."""
import json
import sys
from types import SimpleNamespace

import h5py
import numpy as np
import pytest

from backend.services.sample_scene import prepare_demo_scene, render_sample_scene, scene_composition


def scene_arrays():
    return dict(workpiece_vertices_world_m=np.array([[.8,0,0],[.9,0,0],[.8,.1,0]]),
        workpiece_face_counts=np.array([3]),workpiece_face_indices=np.array([0,1,2]),source_to_scene=np.eye(4),
        environment_layout=np.asarray('stp'),fixture_table_top_m=np.asarray(-.010),
        environment_floor_z_m=np.asarray(-.670),environment_table_center_xy_m=np.array([.860,0]),
        environment_table_size_xy_m=np.array([.500,.800]))


def test_demo_exact_sample_native_placement_exports_no_gt_targets(tmp_path,monkeypatch):
    h5=tmp_path/'B_PR_03_0001.h5';obj=tmp_path/'B_PR_03_0001.obj';obj.write_text('v 1 2 3')
    with h5py.File(h5,'w') as f:f['trajectory']=np.ones((150,6))*123
    calls=[]
    def build(path,sample,poses):
        calls.append((path,sample,poses.copy()));a=scene_arrays();a['gt_world_xyz_m']=poses[:,:3]
        a['target_xyz_m']=poses[:,:3];return poses,a,{}
    def environment(poses,arrays,report,*,layout):
        calls.append(layout);return poses,arrays,{'environment':{'layout':layout}}
    monkeypatch.setitem(sys.modules,'welding_scene_layout',SimpleNamespace(build_scene=build))
    monkeypatch.setitem(sys.modules,'welding_environment',SimpleNamespace(apply_environment=environment))
    result=prepare_demo_scene(h5=h5,obj=obj,sample='B_PR_03_0001',output=tmp_path,backend='dataset_stp')
    assert calls[0][0]==obj and calls[0][1]=='B_PR_03_0001' and calls[1]=='stp'
    assert not result['gt_playback_used'] and result['h5_usage']=='scene placement/orientation metadata only'
    with np.load(tmp_path/'sample_scene.npz') as a:
        assert 'workpiece_vertices_world_m' in a and 'gt_world_xyz_m' not in a and 'target_xyz_m' not in a
    assert json.loads((tmp_path/'sample_scene.json').read_text())['sample_id']=='B_PR_03_0001'


class FakePrim:
    def __init__(self):self.attributes={}
    def __getattr__(self,key):
        return lambda *args:self.attributes.update({key:args}) or self
    def IsValid(self):return True


class FakeStage:
    def __init__(self):self.prims={}
    def GetPrimAtPath(self,path):return self.prims.get(path,SimpleNamespace(IsValid=lambda:False))


@pytest.mark.parametrize('mode',['STRICT','DEMO'])
def test_full_scene_same_table_workpiece_robot_tool_and_prediction(mode):
    stage=FakeStage()
    def define(stage,path):stage.prims[path]=FakePrim();return stage.prims[path]
    geom=SimpleNamespace(Mesh=SimpleNamespace(Define=define),Cube=SimpleNamespace(Define=define))
    gf=SimpleNamespace(Vec3f=lambda *v:v,Vec3d=lambda *v:v)
    render_sample_scene(stage,scene_arrays(),backend='dataset_stp',usd_geom=geom,gf=gf)
    # Robot/tool/path are independently authored by the unchanged native playback renderers.
    path='/DemoPlayback0' if mode=='DEMO' else '/VLA_PREDICTED_9'
    for name in ['/RB10','/Tool/Geometry',path]:define(stage,name)
    assert all(scene_composition(stage,path,backend='dataset_stp').values())
    assert stage.prims['/ReferenceTable'].attributes['CreateSizeAttr']==(1.,)
    assert '/Workpiece' in stage.prims and '/RobotPedestal' in stage.prims
