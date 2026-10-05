"""Offline MJPEG/viewport/renderer checks. No Isaac, external APIs or models."""
import ctypes
import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
import numpy as np
from PIL import Image
import pytest

from backend.agent.config import AgentSettings
from backend.main import create_app
from backend.orchestrator.workflow import Workflow
from backend.services.current_preview_config import CurrentPreviewError
from backend.services.preview_live_producer import LiveFrameProducer, viewport_rgba
from backend.services.preview_visual_style import define_polyline, prediction_style
from tests.agent_fakes import FakeSimulator
from tests.test_preview_capture import runtime_fixture, completion


def frames(runtime):
    output = runtime.session/'outputs'/runtime.latest['request_id']
    identity = {key:runtime.latest[key] for key in ('job_id','artifact_id','session_id','request_id')}
    producer = LiveFrameProducer(output, identity)
    rgba = Image.new('RGBA', (80, 60), 'red').tobytes()
    producer.pump(lambda cb:cb(rgba, len(rgba), 80, 60))
    return producer


def packet(runtime):
    latest = runtime.latest
    return runtime.live_packet(*(latest[k] for k in ('job_id','artifact_id','session_id','request_id')))


def test_producer_throttle_bounded_atomic_jpeg_and_optional_failures(tmp_path):
    clock = [10.]
    producer = LiveFrameProducer(tmp_path, {}, clock=lambda:clock[0])
    calls = []
    rgba = Image.new('RGBA',(1600,900),'red').tobytes()
    def capture(cb):calls.append(True);cb(rgba,len(rgba),1600,900)
    producer.pump(capture);producer.pump(capture)
    assert len(calls)==1
    with Image.open(tmp_path/'live/latest.jpg') as image:
        assert image.format=='JPEG' and image.size==(1280,720)
    clock[0]+=.125
    producer.pump(lambda cb:(_ for _ in ()).throw(RuntimeError('capture failed')))
    assert producer.metadata['sequence']==1 and producer.active
    clock[0]+=.125
    producer.pump(capture)
    assert producer.metadata['sequence']==2 and producer.metadata['warning'] is None
    assert {p.name for p in (tmp_path/'live').iterdir()}=={'latest.jpg','status.json'}
    assert producer.metadata['sha256']==hashlib.sha256((tmp_path/'live/latest.jpg').read_bytes()).hexdigest()
    assert producer.failures==1
    producer.close();clock[0]+=1;producer.pump(capture)
    assert len(calls)==2 and not json.loads((tmp_path/'live/status.json').read_text())['active']


def test_pending_capture_does_not_block_or_queue_and_close_ignores_late_callback(tmp_path):
    clock=[1.];callbacks=[]
    producer=LiveFrameProducer(tmp_path,{},clock=lambda:clock[0])
    producer.pump(callbacks.append)
    clock[0]+=3
    for _ in range(5):producer.pump(callbacks.append)
    assert len(callbacks)==1 and producer.metadata['warning']=='LIVE_CAPTURE_PENDING'
    producer.close();callbacks[0](b'rgba',4,1,1)
    assert not (tmp_path/'live/latest.jpg').exists()


def test_bad_buffer_and_encode_write_failures_skip_only_frame(tmp_path,monkeypatch):
    clock=[1.];p=LiveFrameProducer(tmp_path,{},clock=lambda:clock[0])
    p.pump(lambda cb:cb(b'bad',3,1,1));assert p.failures==1 and p.active
    clock[0]+=1
    monkeypatch.setattr(Image.Image,'save',lambda *a,**k:(_ for _ in ()).throw(OSError('codec')))
    p.pump(lambda cb:cb(b'rgba',4,1,1));assert p.failures==2 and p.active
    with pytest.raises(ValueError):viewport_rgba(b'rgba',4,0,1)


def test_named_kit_capsule_is_copied_during_callback():
    raw=ctypes.create_string_buffer(b'rgba')
    create=ctypes.pythonapi.PyCapsule_New
    create.restype=ctypes.py_object
    create.argtypes=(ctypes.c_void_p,ctypes.c_char_p,ctypes.c_void_p)
    capsule=create(ctypes.addressof(raw),b'viewport',None)
    assert viewport_rgba(capsule,4,1,1)==b'rgba'


def test_bound_live_frame_and_capture_warning_never_changes_playback(tmp_path,monkeypatch):
    runtime,_,_,_,_,launcher=runtime_fixture(tmp_path,monkeypatch)
    try:
        producer=frames(runtime)
        active,data=packet(runtime)
        assert active and data[0]==1 and data[1].startswith(b'\xff\xd8')
        gallery=runtime.preview_frames(runtime.latest['job_id'],runtime.latest['artifact_id'])
        assert gallery['live']['state']=='LIVE' and gallery['live']['available']
        before=runtime.state
        (producer.output/'latest.jpg').write_bytes(b'not jpeg')
        assert packet(runtime)==(True,None) and runtime.state==before and not launcher.child.stopped
        producer.close();assert packet(runtime)==(False,None)
    finally:runtime.close()


def test_unavailable_viewport_and_old_frame_are_optional_and_report_separately(tmp_path,monkeypatch):
    runtime,_,_,_,_,_=runtime_fixture(tmp_path,monkeypatch)
    try:
        p=frames(runtime)
        meta=p.output/'status.json';data=json.loads(meta.read_text())
        data.update(captured_at='2020-01-01T00:00:00+00:00')
        meta.write_text(json.dumps(data))
        gallery=runtime.preview_frames(runtime.latest['job_id'],runtime.latest['artifact_id'])
        assert gallery['live']['state']=='PAUSED' and packet(runtime)==(True,None)
        data.update(sequence=0,warning='LIVE_CAPTURE_API_UNAVAILABLE')
        meta.write_text(json.dumps(data))
        gallery=runtime.preview_frames(runtime.latest['job_id'],runtime.latest['artifact_id'])
        assert gallery['live']['state']=='OFFLINE' and not gallery['live']['available']
        assert runtime.state=='RUNNING_PREVIEW'
    finally:runtime.close()


def test_metadata_publication_race_skips_one_read_then_recovers(tmp_path,monkeypatch):
    from backend.services import current_preview_live
    runtime,_,_,_,_,_=runtime_fixture(tmp_path,monkeypatch)
    try:
        frames(runtime);original=current_preview_live._read;calls=[]
        def racing(context):
            calls.append(True)
            return None if len(calls)==1 else original(context)
        monkeypatch.setattr(current_preview_live,'_read',racing)
        assert packet(runtime)==(True,None)
        assert packet(runtime)[1] and runtime.state=='RUNNING_PREVIEW'
    finally:runtime.close()


@pytest.mark.parametrize('field',['job_id','artifact_id','session_id','request_id'])
def test_stale_stream_identity_is_rejected(tmp_path,monkeypatch,field):
    runtime,_,_,_,_,_=runtime_fixture(tmp_path,monkeypatch)
    try:
        frames(runtime);args={k:runtime.latest[k] for k in ('job_id','artifact_id','session_id','request_id')}
        args[field]=str(uuid4())
        with pytest.raises(CurrentPreviewError):runtime.live_packet(**args)
        assert runtime.state=='RUNNING_PREVIEW'
    finally:runtime.close()


def test_stop_new_request_and_changed_approval_never_serve_old_stream(tmp_path,monkeypatch):
    runtime,client,claim,_,_,_=runtime_fixture(tmp_path,monkeypatch)
    try:
        frames(runtime);assert packet(runtime)[1]
        old={k:runtime.latest[k] for k in ('job_id','artifact_id','session_id','request_id')}
        producer_path=runtime.session/'outputs'/runtime.latest['request_id']/'live'
        # Existing valid completion evidence ends motion independently of MJPEG.
        completion_output=runtime.session/'outputs'/runtime.latest['request_id']
        # completion fixture creates its own output directory; keep frame files elsewhere temporarily.
        moved=completion_output.with_name(completion_output.name+'_test')
        completion_output.rename(moved)
        completion(runtime,claim,());runtime.tick();runtime.submit(claim)
        with pytest.raises(CurrentPreviewError):runtime.live_packet(**old)
        runtime.ready_seen=True;runtime.tick();frames(runtime)
        job=client.storage.get_job(runtime.latest['job_id'])
        client.storage.artifact_path('masks',job.mask.id).write_bytes(b'changed')
        with pytest.raises(CurrentPreviewError) as e:packet(runtime)
        assert e.value.code=='CURRENT_PREVIEW_ARTIFACT_INVALID'
        runtime.stop()
        with pytest.raises(CurrentPreviewError):packet(runtime)
        assert (runtime.session/'stop.json').exists()
    finally:runtime.close()


def test_mjpeg_route_filters_origin_and_uuid_and_finishes_on_stop(tmp_path,monkeypatch):
    runtime,client,_,_,_,launcher=runtime_fixture(tmp_path,monkeypatch)
    frames(runtime)
    jid,aid=runtime.latest['job_id'],runtime.latest['artifact_id']
    url=f'/api/simulator/current-preview/live/{runtime.session.name}/{runtime.latest["request_id"]}?job_id={jid}&artifact_id={aid}'
    original=runtime.live_packet;calls=[]
    def controlled(*args):
        calls.append(True)
        if len(calls)>1:runtime.stop()
        return original(*args)
    monkeypatch.setattr(runtime,'live_packet',controlled)
    with TestClient(create_app(workflow=Workflow(client.storage),simulator=FakeSimulator(),
            current_vla_preview=client,preview_runtime=runtime,agent_settings=AgentSettings(enabled=False))) as api:
        assert api.get(url,headers={'Origin':'https://foreign.invalid'}).status_code==403
        assert api.get(url+'&path=secret').status_code==400
        assert api.get(url.replace(jid,str(uuid4()))).status_code==409
        calls.clear()
        response=api.get(url)
        assert response.status_code==200 and response.headers['content-type'].startswith('multipart/x-mixed-replace; boundary=frame')
        assert b'Content-Type: image/jpeg' in response.content and response.content.endswith(b'--frame--\r\n')
        assert response.headers['cache-control']=='no-store, no-cache'
        assert str(tmp_path).encode() not in response.content
        assert launcher.calls==1 and launcher.child.stopped


@pytest.mark.parametrize('count',[2,9,37])
def test_linear_curve_preserves_all_source_points_and_constant_width(count):
    values=np.arange(count*3,dtype=np.float32).reshape(count,3)*.001
    if count>2:values[2]=values[1]  # Adjacent duplicate stays exactly in source order.
    before=values.copy();record={}
    class Curve:
        def __getattr__(self,name):return lambda value:record.update({name:value})
    usd=SimpleNamespace(BasisCurves=SimpleNamespace(Define=lambda *a:Curve()))
    gf=SimpleNamespace(Vec3f=lambda *p:p)
    style=prediction_style('dataset_stp')
    define_polyline(None,'/VLA',values,style['color'],style['width_m'],usd_geom=usd,gf=gf)
    assert record['CreateTypeAttr']=='linear' and record['CreateWrapAttr']=='nonperiodic'
    assert record['SetWidthsInterpolation']=='constant' and record['CreateWidthsAttr']==[.006]
    assert record['CreateCurveVertexCountsAttr']==[count]
    assert np.array_equal(record['CreatePointsAttr'],before) and np.array_equal(values,before)
    assert style['point_markers'] is False


def test_single_point_and_nonfinite_renderer_are_graceful():
    record={}
    class Sphere:
        def CreateRadiusAttr(self,v):record['radius']=v
        def CreateDisplayColorAttr(self,v):record['color']=v
        def AddTranslateOp(self):return SimpleNamespace(Set=lambda v:record.update(point=v))
    usd=SimpleNamespace(Sphere=SimpleNamespace(Define=lambda *a:Sphere()))
    gf=SimpleNamespace(Vec3f=lambda *p:p,Vec3d=lambda *p:p)
    assert define_polyline(None,'/single',[[1,2,3]],(1,0,0),.006,usd_geom=usd,gf=gf)
    assert record['point']==(1,2,3) and record['radius']==.003
    assert define_polyline(None,'/bad',[[float('nan'),1,2]],(1,0,0),.006,usd_geom=usd,gf=gf) is None


def test_exact_pre_live_upgrade_preserves_every_native_source_and_previous_descriptor(tmp_path):
    import copy
    from pathlib import Path
    from backend.refresh_preview_ux import refresh, PRE_LIVE_OWNED_CODE
    from backend.services.current_preview_gate import read, sha, verify_preview
    from tests.test_simulator_stp_client import fixture
    client,job,attempt=fixture(tmp_path)
    old=client.prepare(job_id=job.id,kind='robot');d=read(old['path'])
    d['owned_code']=copy.deepcopy(PRE_LIVE_OWNED_CODE['dataset_stp'])
    Path(old['path']).write_text(json.dumps(d));old['sha256']=sha(old['path'])
    cache=client.settings.project/'.cache/simulator-stp/readiness'/d['artifact_id']/'robot.json'
    cache.write_text(json.dumps(old))
    package=Path(d['package']).parent
    files=[p for p in package.rglob('*') if p.is_file()]+[Path(old['path']),attempt/'trajectory.npz',
        client.storage.artifact_path('jobs',job.id,'.json'),client.storage.artifact_path('masks',job.mask.id)]
    before={p:sha(p) for p in files}
    fresh=refresh(d['artifact_id'],project=client.settings.project)
    new,_,_=verify_preview(fresh,project=client.settings.project)
    assert new['package_id']==d['package_id'] and new['source_to_scene']==d['source_to_scene']
    assert 'backend/services/preview_live_producer.py' in new['owned_code']
    assert new['vla_orientation'] is False and new['physical_robot_executable'] is False
    assert all(sha(p)==digest for p,digest in before.items())
    assert len(client.builder.calls)==1 and not client.runtime.calls
