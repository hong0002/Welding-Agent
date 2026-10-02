"""Owned latest captures only. Fake native builder/process; no GUI or model calls."""
import json
from pathlib import Path
from uuid import uuid4

from PIL import Image
import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.agent.config import AgentSettings
from backend.orchestrator.workflow import Workflow
from backend.services.current_preview_config import CurrentPreviewError
from backend.services.current_preview_gate import read, sha, verify_preview
from backend.services.preview_capture import CAPTURE_NAMES
from tests.agent_fakes import FakeSimulator
from tests.test_preview_capture import runtime_fixture, completion


def captures(runtime):
    output=runtime.session/'outputs'/runtime.latest['request_id']
    output.mkdir(parents=True,exist_ok=True)
    for name in CAPTURE_NAMES:
        Image.new('RGB',(80,60),'red').save(output/(name+'.png'))
    return output


def ids(runtime):
    return runtime.latest['job_id'],runtime.latest['artifact_id']


def test_active_captures_recheck_proof_and_never_dispatch(tmp_path,monkeypatch):
    runtime,client,claim,attempt,builder,launcher=runtime_fixture(tmp_path,monkeypatch)
    protected=(attempt/'trajectory.npz',Path(read(claim['path'])['package']))
    before={p:sha(p) for p in protected}
    try:
        captures(runtime)
        gallery=runtime.preview_frames(*ids(runtime))
        assert gallery['available'] and gallery['delivery']=='latest_capture'
        assert [f['name'] for f in gallery['frames']]==list(CAPTURE_NAMES)
        assert gallery['session_id']==runtime.session.name
        assert str(tmp_path) not in json.dumps(gallery)
        f=gallery['frames'][0]
        image=runtime.preview_frame(*ids(runtime),gallery['session_id'],gallery['request_id'],f['name'],f['sha256'])
        assert image.startswith(b'\x89PNG') and sha(protected[0])==before[protected[0]]
        assert launcher.calls==len(builder.calls)==1 and not client.runtime.calls
        assert all(sha(p)==digest for p,digest in before.items())
        # A current approval edit hides the frame without rebuilding a prediction.
        job=client.storage.get_job(ids(runtime)[0])
        client.storage.artifact_path('masks',job.mask.id).write_bytes(b'changed approval')
        with pytest.raises(CurrentPreviewError) as error:runtime.preview_frames(*ids(runtime))
        assert error.value.code=='CURRENT_PREVIEW_ARTIFACT_INVALID'
    finally:runtime.close()


@pytest.mark.parametrize('change',['job','artifact','session','request','digest'])
def test_wrong_identity_never_reads_other_capture(tmp_path,monkeypatch,change):
    runtime,_,_,_,_,launcher=runtime_fixture(tmp_path,monkeypatch)
    try:
        captures(runtime);gallery=runtime.preview_frames(*ids(runtime));f=gallery['frames'][0]
        args=[*ids(runtime),gallery['session_id'],gallery['request_id'],f['name'],f['sha256']]
        index={'job':0,'artifact':1,'session':2,'request':3,'digest':5}[change]
        args[index]='0'*64 if change=='digest' else str(uuid4())
        with pytest.raises(CurrentPreviewError) as error:runtime.preview_frame(*args)
        assert error.value.code==('CURRENT_PREVIEW_FRAME_UNAVAILABLE' if change=='digest' else 'CURRENT_PREVIEW_FRAME_STALE')
        assert launcher.calls==1
    finally:runtime.close()


@pytest.mark.parametrize('state',['STOPPED','FAILED'])
def test_stop_or_failed_never_returns_historical_frame(tmp_path,monkeypatch,state):
    runtime,_,_,_,_,launcher=runtime_fixture(tmp_path,monkeypatch)
    try:
        captures(runtime);gallery=runtime.preview_frames(*ids(runtime));f=gallery['frames'][0]
        runtime.stop() if state=='STOPPED' else runtime._fail('fake process failure')
        assert not runtime.preview_frames(*ids(runtime))['available']
        with pytest.raises(CurrentPreviewError):
            runtime.preview_frame(*ids(runtime),gallery['session_id'],gallery['request_id'],f['name'],f['sha256'])
        assert launcher.calls==1
    finally:runtime.close()


def test_ready_capture_failure_does_not_fail_playback(tmp_path,monkeypatch):
    runtime,_,claim,_,_,launcher=runtime_fixture(tmp_path,monkeypatch)
    try:
        output,_,_=completion(runtime,claim,())
        # Completion evidence can succeed while a PNG is unavailable to the viewer.
        runtime.tick();assert runtime.state=='READY'
        gallery=runtime.preview_frames(*ids(runtime))
        assert not gallery['available'] and gallery['reason_code']=='CURRENT_PREVIEW_FRAME_UNAVAILABLE'
        assert runtime.latest['playback_status']=='SUCCEEDED' and not launcher.child.stopped
        Image.new('RGB',(80,60),'red').save(output/'P0.png')
        assert runtime.preview_frames(*ids(runtime))['available']
    finally:runtime.close()


def test_changed_capture_hash_and_old_request_are_not_cached(tmp_path,monkeypatch):
    runtime,_,claim,_,_,_=runtime_fixture(tmp_path,monkeypatch)
    try:
        completion(runtime,claim,());runtime.tick();output=captures(runtime)
        gallery=runtime.preview_frames(*ids(runtime));f=gallery['frames'][0]
        Image.new('RGB',(80,60),'blue').save(output/'P0.png')
        with pytest.raises(CurrentPreviewError):
            runtime.preview_frame(*ids(runtime),gallery['session_id'],gallery['request_id'],f['name'],f['sha256'])
        runtime.submit(claim)
        assert runtime.latest['request_id']!=gallery['request_id']
        assert not runtime.preview_frames(*ids(runtime))['available']
        with pytest.raises(CurrentPreviewError):
            runtime.preview_frame(*ids(runtime),gallery['session_id'],gallery['request_id'],f['name'],f['sha256'])
    finally:runtime.close()


def test_capture_symlink_and_non_png_are_never_served(tmp_path,monkeypatch):
    runtime,_,_,_,_,_=runtime_fixture(tmp_path,monkeypatch)
    try:
        output=captures(runtime);outside=tmp_path/'private.png'
        Image.new('RGB',(80,60),'green').save(outside)
        # Simulate resolution through a link on hosts that cannot create symlinks.
        original=Path.resolve
        monkeypatch.setattr(Path,'resolve',lambda p,*a,**kw:outside if p==output/'P0.png' else original(p,*a,**kw))
        (output/'P4.png').write_bytes(b'secret non-image payload')
        gallery=runtime.preview_frames(*ids(runtime))
        assert [f['name'] for f in gallery['frames']]==['P8','path_detail']
    finally:runtime.close()


def test_read_only_api_uuid_allowlist_no_store_and_safe_rejections(tmp_path,monkeypatch):
    runtime,client,_,_,builder,launcher=runtime_fixture(tmp_path,monkeypatch)
    captures(runtime)
    with TestClient(create_app(workflow=Workflow(client.storage),simulator=FakeSimulator(),
            current_vla_preview=client,preview_runtime=runtime,agent_settings=AgentSettings(enabled=False))) as api:
        jid,aid=ids(runtime);url=f'/api/simulator/current-preview/frames?job_id={jid}&artifact_id={aid}'
        response=api.get(url)
        assert response.status_code==200 and response.headers['cache-control']=='no-store'
        frame=response.json()['frames'][0]
        image=api.get(frame['url'])
        assert image.status_code==200 and image.headers['content-type']=='image/png'
        assert image.headers['cache-control']=='no-store' and image.headers['x-content-type-options']=='nosniff'
        assert str(tmp_path).encode() not in image.content
        assert api.get(url+'&path=private.png').status_code==400
        assert api.get(frame['url'].replace('/P0/','/private/')).status_code==422
        assert api.get(url.replace(jid,str(uuid4()))).json()['code']=='CURRENT_PREVIEW_FRAME_STALE'
        assert launcher.calls==len(builder.calls)==1 and not client.runtime.calls
        runtime.stop()
        assert not api.get(url).json()['available'] and api.get(frame['url']).status_code==409
