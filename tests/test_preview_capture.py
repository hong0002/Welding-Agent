"""Fake viewport/process tests only; no Isaac, model, or external native execution."""
import json
from pathlib import Path
import sys

import numpy as np
import pytest

from backend.services.preview_capture import CaptureDiagnostics, play_waypoints, CAPTURE_NAMES
from backend.services.current_preview_runtime import CurrentPreviewRuntime
from backend.services.simulator_client import SimulatorConfig
from backend.services.current_preview_gate import verify_preview, read, sha
from tests.test_simulator import FakeProcess
from tests.test_simulator2_client import client_fixture


@pytest.mark.parametrize('failed', [(), ('P0',), ('P4',), CAPTURE_NAMES])
def test_optional_capture_continues_original_playback(tmp_path, failed):
    output=tmp_path/'evidence_한글';output.mkdir()
    stage=tmp_path/'ascii_stage';stage.mkdir()
    clock=[0.];events=[];visited=[];api_paths=[]
    source=np.arange(27,dtype=np.float32).reshape(9,3)
    original=source.copy()
    diag=CaptureDiagnostics(output, lambda stage,**kw:events.append(dict(stage=stage,**kw)),
        clock=lambda:clock[0],timeout=.2,staging_factory=lambda:stage)
    def update():clock[0]+=.05
    def capture(index):
        if index not in (0,4,8):return
        name='P'+str(index)
        def request(path):
            api_paths.append(path)
            if name=='P4' and name in failed:raise RuntimeError('private path/payload')
            if name not in failed:Path(path).write_bytes(b'png'*500)
        diag.attempt(name,request_capture=request,update=update)
    play_waypoints(9,lambda i:visited.append(i),capture)
    diag.attempt('path_detail',request_capture=lambda p:None if 'path_detail' in failed else Path(p).write_bytes(b'png'*500),update=update)
    summary=diag.summary()
    assert visited==list(range(9)) and np.array_equal(source,original)
    assert all(p.isascii() and str(output) not in p for p in api_paths)
    assert summary['capture_status']==('FAILED' if len(failed)==4 else 'PARTIAL_FAILED' if failed else 'SUCCEEDED')
    assert len(summary['captures'])==4-len(failed)
    assert all((output/name).is_file() for name in summary['captures'])
    assert 'private path' not in json.dumps(events) and str(tmp_path) not in json.dumps(events)
    if 'P0' in failed:assert 'CAPTURE_FILE_MISSING_TIMEOUT' in summary['capture_warning_codes']
    if 'P4' in failed:assert 'CAPTURE_API_FAILED' in summary['capture_warning_codes']


@pytest.mark.parametrize('size,code', [(0,'CAPTURE_ZERO_BYTE'),(20,'CAPTURE_FILE_INCOMPLETE')])
def test_zero_or_incomplete_capture_is_warning(tmp_path,size,code):
    clock=[0.]
    diag=CaptureDiagnostics(tmp_path,lambda *a,**k:None,clock=lambda:clock[0],timeout=.1,staging_factory=lambda:tmp_path)
    def update():clock[0]+=.1
    diag.attempt('P0',request_capture=lambda p:Path(p).write_bytes(b'x'*size),update=update)
    assert diag.summary()['capture_warning_codes']==[code]


def test_non_ascii_staging_never_reaches_viewport(tmp_path):
    stage=tmp_path/'한글';stage.mkdir();calls=[]
    diag=CaptureDiagnostics(tmp_path,lambda *a,**k:None,staging_factory=lambda:stage)
    diag.attempt('P0',request_capture=lambda p:calls.append(p),update=lambda:None)
    assert not calls and diag.summary()['capture_warning_codes']==['CAPTURE_ASCII_PATH_UNAVAILABLE']


def test_scene_update_failure_inside_capture_remains_fatal(tmp_path):
    diag=CaptureDiagnostics(tmp_path,lambda *a,**k:None,staging_factory=lambda:tmp_path)
    def update():raise RuntimeError('core scene update failed')
    with pytest.raises(RuntimeError,match='core scene'):
        diag.attempt('P0',request_capture=lambda p:None,update=update)


def runtime_fixture(tmp_path,monkeypatch):
    client,job,_,attempt,builder,_=client_fixture(tmp_path)
    claim=client.prepare(job_id=job.id)
    monkeypatch.setattr('backend.services.current_preview_runtime.verify_preview',
        lambda c:verify_preview(c,project=client.settings.project))
    class Launcher:
        calls=0
        def preview(self,*a):self.calls+=1;self.child=FakeProcess(123);return self.child
    launcher=Launcher()
    config=SimulatorConfig(root=client.root,python=Path(sys.executable),runtime_dir=tmp_path/'runtime',
        sample_id=None,data_root=None,prediction_root=None)
    runtime=CurrentPreviewRuntime(config,launcher=launcher,monitor=False,backend='dataset_v2')
    monkeypatch.setattr(runtime,'check_configuration',lambda **kw:None)
    runtime.submit(claim);runtime.ready_seen=True;runtime.tick()
    return runtime,client,claim,attempt,builder,launcher


def completion(runtime,claim,failed):
    d=read(claim['path']);package=Path(d['package']).parent
    output=runtime.session/'outputs'/runtime.latest['request_id'];output.mkdir(parents=True)
    with np.load(package/'native/trajectory_solution.npz') as native, np.load(package/'predictions'/d['sample_id']/'trajectory.npz') as source:
        targets=native['tcp_pose_xyz_mm_rpy_deg'][:,:3]*.001
        np.savez(output/'waypoints.npz',predicted_path_m=source['predicted_path_m'],ground_truth_path_m=source['ground_truth_path_m'],
            source_to_scene=np.asarray(d['source_to_scene']),playback_target_world_m=targets,
            measured_tip_world_m=targets,playback_waypoint_parameter=native['playback_waypoint_parameter'])
    (output/'scene.usda').write_bytes(b'x'*1200)
    diag=[dict(name=n,status='FAILED' if n in failed else 'SUCCEEDED',
               reason_code='CAPTURE_FILE_MISSING_TIMEOUT' if n in failed else None) for n in CAPTURE_NAMES]
    for n in CAPTURE_NAMES:
        if n not in failed:(output/(n+'.png')).write_bytes(b'png'*500)
    data=dict(state='done',artifact_id=d['artifact_id'],package_id=d['package_id'],point_count=9,
        fixture_ready=False,physical_robot_executable=False,exact_xyz_preserved=True,robot_motion=True,
        backend='dataset_v2',source_point_count=9,playback_point_count=17,playback_derived=True,sample_family='B_PP',
        physics_stepping=False,gt_is_target=False,playback_status='SUCCEEDED',completed_playback_points=17,
        displayed_playback_points=17,capture_diagnostics=diag,
        robot_visual_meshes=[dict(finite=True,prim_created=True)])
    (output/'report.json').write_text(json.dumps(data),encoding='utf-8')
    result=runtime.session/'results'/(runtime.latest['request_id']+'.json')
    result.write_text(json.dumps(data),encoding='utf-8')
    return output,result,data


@pytest.mark.parametrize('failed',[(),('P0',),('P4',),CAPTURE_NAMES])
def test_runtime_optional_capture_holds_gui_ready_until_stop(tmp_path,monkeypatch,failed):
    runtime,client,claim,attempt,builder,launcher=runtime_fixture(tmp_path,monkeypatch)
    protected=(attempt/'trajectory.npz',Path(read(claim['path'])['package']).parent/'native/trajectory_solution.npz')
    before={p:sha(p) for p in protected}
    try:
        completion(runtime,claim,failed);runtime.tick()
        assert runtime.state=='READY' and runtime.latest['status']=='SUCCEEDED'
        assert runtime.latest['playback_status']=='SUCCEEDED'
        assert runtime.latest['capture_status']==('FAILED' if len(failed)==4 else 'PARTIAL_FAILED' if failed else 'SUCCEEDED')
        assert runtime.latest['reason_code']==('SIMULATOR2_CAPTURE_WARNING' if failed else None)
        assert runtime.latest['source_point_count']==9 and runtime.latest['playback_point_count']==17
        assert runtime.process is not None and not launcher.child.stopped and runtime.lease is not None
        runtime.tick();assert runtime.state=='READY'
        assert all(sha(p)==digest for p,digest in before.items()) and len(builder.calls)==launcher.calls==1
    finally:runtime.close()
    assert launcher.child.stopped and runtime.lease is None


@pytest.mark.parametrize('phase',['waypoint_P1','robot_visuals','stage_geometry'])
def test_actual_fk_robot_visual_scene_failure_remains_fatal(tmp_path,monkeypatch,phase):
    runtime,_,_,_,_,launcher=runtime_fixture(tmp_path,monkeypatch)
    try:
        result=runtime.session/'results'/(runtime.latest['request_id']+'.json')
        result.write_text(json.dumps(dict(state='failed',phase=phase,exception_class='RuntimeError')))
        runtime.tick()
        assert runtime.state=='FAILED' and runtime.latest['playback_status']=='FAILED'
        assert runtime.latest['reason_code']=='SIMULATOR2_PLAYBACK_FAIL' and launcher.child.stopped
        assert launcher.calls==1 and runtime.lease is None
    finally:runtime.close()


@pytest.mark.parametrize('bad',['partial','xyz','visual','scene'])
def test_capture_warning_cannot_hide_incomplete_or_changed_playback(tmp_path,monkeypatch,bad):
    runtime,_,claim,_,_,launcher=runtime_fixture(tmp_path,monkeypatch)
    try:
        output,result,data=completion(runtime,claim,CAPTURE_NAMES)
        if bad=='scene':(output/'scene.usda').unlink()
        elif bad=='xyz':
            with np.load(output/'waypoints.npz') as source:arrays={k:source[k].copy() for k in source.files}
            arrays['predicted_path_m'][0,0]+=1
            np.savez(output/'waypoints.npz',**arrays)
        else:
            if bad=='partial':data['completed_playback_points']=1
            if bad=='visual':data['robot_visual_meshes']=[]
            (output/'report.json').write_text(json.dumps(data));result.write_text(json.dumps(data))
        runtime.tick()
        assert runtime.state=='FAILED' and launcher.child.stopped
    finally:runtime.close()


def test_capture_rebind_reuses_immutable_native_package_no_recompute(tmp_path,monkeypatch):
    from backend.refresh_capture_descriptor import refresh
    client,job,_,_,builder,_=client_fixture(tmp_path)
    old=client.prepare(job_id=job.id);d=read(old['path']);p=Path(d['package'])
    # Represent a fixed audited previous release; migration never accepts arbitrary code.
    previous={k:v for k,v in d['owned_code'].items() if k!='backend/services/preview_capture.py'}
    previous['backend/current_vla_isaac_preview.py']='a'*64
    d['owned_code']=previous
    Path(old['path']).write_text(json.dumps(d));old['sha256']=sha(old['path'])
    cache=client.settings.project/'.cache/simulator2/readiness'/d['artifact_id']/'robot.json'
    cache.write_text(json.dumps(old))
    monkeypatch.setattr('backend.refresh_capture_descriptor.PRE_CAPTURE_OWNED_CODE',previous)
    before={x:sha(x) for x in (p,p.parent/'native/trajectory_solution.npz',Path(old['path']))}
    fresh=refresh(d['artifact_id'],project=client.settings.project)
    new,_,_=verify_preview(fresh,project=client.settings.project)
    assert fresh!=old and new['package_id']==d['package_id'] and new['source_to_scene']==d['source_to_scene']
    assert all(sha(x)==digest for x,digest in before.items()) and len(builder.calls)==1 and not client.runtime.calls
    assert refresh(d['artifact_id'],project=client.settings.project)==fresh


def test_capture_rebind_rejects_unknown_release(tmp_path):
    from backend.refresh_capture_descriptor import refresh
    client,job,_,_,builder,_=client_fixture(tmp_path)
    old=client.prepare(job_id=job.id);d=read(old['path'])
    d['owned_code']['backend/current_vla_isaac_preview.py']='f'*64
    Path(old['path']).write_text(json.dumps(d));old['sha256']=sha(old['path'])
    cache=client.settings.project/'.cache/simulator2/readiness'/d['artifact_id']/'robot.json';cache.write_text(json.dumps(old))
    with pytest.raises(ValueError,match='not the audited'):refresh(d['artifact_id'],project=client.settings.project)
    assert read(cache)==old and len(builder.calls)==1 and not client.runtime.calls
