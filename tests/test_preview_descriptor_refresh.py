"""Descriptor-only migration and pre-GUI diagnostics. Fake native outputs only."""
import io
import json
from pathlib import Path
import sys
import subprocess
from uuid import uuid4

from fastapi.testclient import TestClient
import numpy as np
import pytest

from backend.agent.config import AgentSettings
from backend.main import create_app
from backend.orchestrator.workflow import Workflow
from backend.refresh_preview_ux import FINAL_PROOF_CODE, refresh, refresh_current
from backend.services.current_preview_gate import read, sha, verify_preview
from backend.services.current_preview_runtime import CurrentPreviewRuntime
from backend.services.preview_startup import MESSAGES, run_preview
from backend.services.simulator_client import SimulatorConfig
from tests.agent_fakes import FakeSimulator
from tests.test_gpt_simulator_handoff import gpt_fixture
from tests.test_simulator import FakeProcess
from tests.test_simulator2_client import client_fixture
from tests.test_simulator_stp_client import fixture


def legacy(client, job, kind='robot'):
    claim = client.prepare(job_id=job.id, kind=kind)
    d = read(claim['path'])
    del d['owned_code'][FINAL_PROOF_CODE]
    Path(claim['path']).write_text(json.dumps(d), encoding='utf-8')
    claim['sha256'] = sha(claim['path'])
    cache = client.settings.project/'.cache'/client.cache_namespace/'readiness'/d['artifact_id']/(kind+'.json')
    cache.write_text(json.dumps(claim), encoding='utf-8')
    return claim, d, cache


@pytest.mark.parametrize('provider', ['guided_vla', 'gpt', 'dataset_v2'])
@pytest.mark.parametrize('kind', ['path', 'robot'])
def test_missing_proof_reproduced_then_explicit_migration_preserves_every_source(tmp_path, provider, kind):
    if provider == 'dataset_v2':
        client, job, _, attempt, *_ = client_fixture(tmp_path)
    else:
        client, job, attempt = (gpt_fixture if provider == 'gpt' else fixture)(tmp_path)
    claim, d, cache = legacy(client, job, kind)
    with pytest.raises(ValueError, match='Native/owned code fingerprint missing'):
        verify_preview(claim, project=client.settings.project)
    package = read(d['package'])
    protected = [p for p in Path(d['package']).parent.rglob('*') if p.is_file()]
    protected += [p for p in attempt.rglob('*') if p.is_file()]
    protected += [Path(claim['path']), Path(package['h5']), Path(package['obj']),
                  client.storage.artifact_path('jobs', job.id, '.json'), client.storage.artifact_path('masks', job.mask.id)]
    before = {p: sha(p) for p in protected}
    fresh = refresh(d['artifact_id'], backend=client.backend, project=client.settings.project, kind=kind, job_id=job.id)
    new, _, _ = verify_preview(fresh, project=client.settings.project)
    assert fresh != claim and read(cache) == fresh
    assert new['owned_code'][FINAL_PROOF_CODE] == sha(Path(__file__).resolve().parents[1]/FINAL_PROOF_CODE)
    assert all(new['owned_code'][k] == v for k, v in d['owned_code'].items())
    assert new['source_point_count'] == new['point_count'] == (33 if provider == 'gpt' else 9)
    assert new['ux_renderer_refresh']['reason'] == 'FINAL_PREDICTION_PROOF_FINGERPRINT_ADDED'
    assert new['ux_renderer_refresh']['previous_descriptor'] == claim
    assert all(sha(p) == digest for p, digest in before.items())
    assert len(client.builder.calls) == 1 and not client.runtime.calls
    assert new['vla_orientation'] is False and new['physical_robot_executable'] is False
    # Idempotent explicit refresh does not create a second new descriptor.
    assert refresh(d['artifact_id'], backend=client.backend, project=client.settings.project, kind=kind, job_id=job.id) == fresh


@pytest.mark.parametrize('change', ['code', 'artifact', 'wrong_job', 'sample', 'foreign', 'extra_missing', 'changed_approval'])
def test_tamper_and_unknown_contract_never_heal(tmp_path, change):
    client, job, attempt = fixture(tmp_path)
    claim, d, cache = legacy(client, job)
    if change == 'code': d['owned_code'][next(iter(d['owned_code']))] = '0'*64
    elif change == 'artifact': (attempt/'trajectory.npz').write_bytes(b'tampered source')
    elif change == 'wrong_job': d['job_id'] = str(uuid4())
    elif change == 'sample': d['sample_id'] = 'B_PP_03_0002'
    elif change == 'extra_missing': d['owned_code'].pop(next(iter(d['owned_code'])))
    elif change == 'changed_approval':
        job.mask.approved_at = job.mask.approved_at.replace(year=2025)
        client.storage.save_job(job)
    Path(claim['path']).write_text(json.dumps(d), encoding='utf-8')
    claim['sha256'] = sha(claim['path'])
    if change == 'foreign':
        foreign = tmp_path/'foreign'/str(uuid4())/'preview.json'
        foreign.parent.mkdir(parents=True)
        foreign.write_bytes(Path(claim['path']).read_bytes())
        claim = dict(path=str(foreign), sha256=sha(foreign))
    cache.write_text(json.dumps(claim), encoding='utf-8')
    root = client.settings.project/'.cache/simulator/current-previews/packages'
    files = {p: sha(p) for p in root.rglob('*') if p.is_file()}
    cache_before = cache.read_bytes()
    with pytest.raises((ValueError, OSError)):
        refresh(d['artifact_id'], project=client.settings.project, job_id=job.id)
    assert cache.read_bytes() == cache_before
    assert {p: sha(p) for p in root.rglob('*') if p.is_file()} == files
    assert len(client.builder.calls) == 1 and not client.runtime.calls


def test_refresh_api_current_identity_only_and_zero_dispatch(tmp_path):
    client, job, _ = fixture(tmp_path)
    for kind in ('path', 'robot'): legacy(client, job, kind)
    with TestClient(create_app(workflow=Workflow(client.storage), simulator=FakeSimulator(),
                              current_vla_preview=client, preview_runtime=client.runtime,
                              agent_settings=AgentSettings(enabled=False))) as api:
        url = '/api/simulator/current-vla/preview-descriptor-refresh'
        assert api.post(url, json={'job_id': str(job.id), 'path': 'foreign'}).status_code == 422
        assert api.post(url, json={'job_id': str(job.id)}, headers={'Origin':'https://foreign.invalid'}).status_code == 403
        assert api.post(url, json={'artifact_id': str(job.vla_prediction.artifact_id)}).status_code == 409
        result = api.post(url, json={'job_id': str(job.id)})
        assert result.status_code == 200
        assert {p['kind'] for p in result.json()['previews']} == {'path', 'robot'}
        assert all(p['changed'] for p in result.json()['previews'])
        assert result.json()['native_recomputed'] is result.json()['isaac_launched'] is False
        assert str(tmp_path) not in result.text
        assert client.capabilities(job_id=job.id)['robot_preview_ready']
        assert len(client.builder.calls) == 2 and not client.runtime.calls


def test_both_descriptors_checked_before_migration_and_no_busy_refresh(tmp_path):
    client, job, _ = fixture(tmp_path)
    _, _, cache = legacy(client, job, 'path')
    legacy(client, job, 'robot')
    robot = cache.with_name('robot.json')
    robot.write_text(json.dumps(dict(path='foreign', sha256='0'*64)))
    before = cache.read_bytes()
    from backend.services.current_preview_config import CurrentPreviewError
    with pytest.raises(CurrentPreviewError, match='refresh rejected'):
        refresh_current(client, job.id)
    assert cache.read_bytes() == before
    client.runtime.status = lambda: {'can_stop': True}
    with pytest.raises(CurrentPreviewError, match='Stop the current preview'):
        refresh_current(client, job.id)


def owned_session(client, claim):
    session = client.settings.project/'.cache/simulator/current-previews/sessions'/str(uuid4())
    (session/'queue').mkdir(parents=True);(session/'results').mkdir()
    request = str(uuid4()); d = read(claim['path'])
    (session/'catalog.json').write_text(json.dumps({d['artifact_id']: claim}))
    (session/'queue'/(request+'.json')).write_text(json.dumps(dict(type='preview_current_vla',
        artifact_id=d['artifact_id'], kind=d['kind'], mode='unvalidated')))
    return session, dict(session=str(session), first_request=request)


@pytest.mark.parametrize('case', ['admission', 'startup'])
def test_before_gui_exception_persists_bound_safe_result_and_log(tmp_path, capsys, case):
    client, job, _ = fixture(tmp_path)
    claim = legacy(client, job)[0] if case == 'admission' else client.prepare(job_id=job.id)
    session, options = owned_session(client, claim)
    calls = []
    def renderer(_):
        calls.append(True)
        raise RuntimeError('token=secret123 C:\\private\\payload raw request')
    before = set(sys.modules)
    with pytest.raises(SystemExit) as exc:
        run_preview(options, project=client.settings.project, renderer=renderer)
    assert exc.value.code == 1 and calls == ([] if case == 'admission' else [True])
    result = read(session/'results'/(options['first_request']+'.json'))
    assert result['stage'] == 'preview_'+case
    assert result['reason_code'] == ('OWNED_CODE_FINGERPRINT_MISSING' if case == 'admission' else 'PREVIEW_STARTUP_FAILED')
    assert result['exception_class'] == ('ValueError' if case == 'admission' else 'RuntimeError')
    assert result['exit_code'] == 1 and result['request_id'] == options['first_request']
    combined = (session/'startup.native.log').read_text()+capsys.readouterr().out+json.dumps(result)
    assert 'secret123' not in combined and str(tmp_path) not in combined and 'raw request' not in combined
    assert not any(n.startswith(('isaacsim','omni')) for n in set(sys.modules)-before)


def test_foreign_session_does_not_get_error_files(tmp_path):
    foreign = tmp_path/str(uuid4());foreign.mkdir()
    with pytest.raises(ValueError, match='backend-owned'):
        run_preview(dict(session=str(foreign), first_request=str(uuid4())), project=tmp_path)
    assert not list(foreign.iterdir())


def test_startup_diagnostics_import_without_backend_or_isaac_dependencies():
    code = """import sys
class Deny:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'PIL','pydantic','numpy','isaacsim','omni'}:
            raise ImportError('Third-party startup import forbidden')
sys.meta_path.insert(0, Deny())
from backend.services.preview_startup import run_preview
print('STDLIB_STARTUP_IMPORT_PASS')
"""
    result = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == 'STDLIB_STARTUP_IMPORT_PASS'


def runtime_for(client, job, tmp_path, monkeypatch, kind):
    claim = client.prepare(job_id=job.id, kind=kind)
    monkeypatch.setattr('backend.services.current_preview_runtime.verify_preview',
                        lambda c: verify_preview(c, project=client.settings.project))
    child = FakeProcess(123)
    class Launcher:
        def preview(self, *args): return child
    runtime = CurrentPreviewRuntime(SimulatorConfig(root=client.root, python=Path(sys.executable),
        runtime_dir=tmp_path/'runtime', sample_id=None, data_root=None, prediction_root=None),
        launcher=Launcher(), monitor=False, backend=client.backend)
    monkeypatch.setattr(runtime, 'check_configuration', lambda **kw: None)
    runtime.submit(claim)
    return runtime, claim, child


def test_exit_before_ready_uses_sanitized_bound_reason_and_logs(tmp_path, monkeypatch):
    client, job, _ = fixture(tmp_path)
    runtime, _, child = runtime_for(client, job, tmp_path, monkeypatch, 'robot')
    try:
        result = dict(state='failed', stage='preview_admission', reason_code='OWNED_CODE_FINGERPRINT_MISSING',
                      request_id=runtime.latest['request_id'], session_id=runtime.session.name,
                      message='private C:\\path token=secret123')
        (runtime.session/'results'/(runtime.latest['request_id']+'.json')).write_text(json.dumps(result))
        child.stdout = io.StringIO('[CURRENT_PREVIEW] safe startup failure\n')
        runtime._read(child)
        child.code = 1;runtime.tick()
        assert runtime.state == 'FAILED' and runtime.latest['failure_stage'] == 'preview_admission'
        assert runtime.latest['reason_code'] == 'OWNED_CODE_FINGERPRINT_MISSING' and runtime.latest['exit_code'] == 1
        assert runtime.error == MESSAGES['OWNED_CODE_FINGERPRINT_MISSING']
        assert 'secret123' not in json.dumps(runtime.status())
        assert 'safe startup failure' in (runtime.session/'native.log').read_text()
        assert child.stopped and runtime.lease is None
    finally: runtime.close()


@pytest.mark.parametrize('kind', ['path', 'robot'])
@pytest.mark.parametrize('provider', ['guided_vla', 'gpt'])
def test_completion_keeps_admitted_nine_or_33_contract(tmp_path, monkeypatch, provider, kind):
    client, job, _ = (gpt_fixture if provider == 'gpt' else fixture)(tmp_path)
    runtime, claim, child = runtime_for(client, job, tmp_path, monkeypatch, kind)
    try:
        d = read(claim['path']);package = Path(d['package']).parent
        output = runtime.session/'outputs'/runtime.latest['request_id'];output.mkdir(parents=True)
        with np.load(package/'native/trajectory_solution.npz') as native, np.load(package/'predictions'/d['sample_id']/'trajectory.npz') as source:
            transform = np.asarray(d['source_to_scene'])
            targets = native['tcp_pose_xyz_mm_rpy_deg'][:,:3]*.001 if kind == 'robot' else source['predicted_path_m'].astype(float) @ transform[:3,:3].T + transform[:3,3]
            parameters = native['playback_waypoint_parameter'] if kind == 'robot' else np.arange(d['point_count'])
            np.savez(output/'waypoints.npz', predicted_path_m=source['predicted_path_m'], ground_truth_path_m=source['ground_truth_path_m'],
                     source_to_scene=transform, playback_target_world_m=targets, measured_tip_world_m=targets, playback_waypoint_parameter=parameters)
        (output/'scene.usda').write_bytes(b'x'*1200)
        data = dict(state='done', artifact_id=d['artifact_id'], package_id=d['package_id'], point_count=d['point_count'],
            fixture_ready=False, physical_robot_executable=False, exact_xyz_preserved=True, robot_motion=kind=='robot',
            backend=client.backend, source_point_count=d['point_count'], playback_point_count=d['playback_point_count'],
            playback_derived=True, sample_family=d['family'], physics_stepping=False, gt_is_target=False,
            playback_status='SUCCEEDED', completed_playback_points=len(targets), displayed_playback_points=len(targets),
            capture_diagnostics=[dict(name=n, status='FAILED', reason_code='CAPTURE_FILE_MISSING_TIMEOUT') for n in ('P0','P4','P8','path_detail')],
            robot_visual_meshes=[dict(finite=True, prim_created=True)])
        (output/'report.json').write_text(json.dumps(data))
        (runtime.session/'results'/(runtime.latest['request_id']+'.json')).write_text(json.dumps(data))
        runtime.ready_seen=True;runtime.tick()
        assert runtime.latest['status'] == 'SUCCEEDED' and runtime.state == 'READY'
        assert runtime.latest['point_count'] == (33 if provider == 'gpt' else 9)
        assert runtime.latest['capture_status'] == 'FAILED' and not child.stopped
    finally: runtime.close()
