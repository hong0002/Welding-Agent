"""Configuration/admission regressions; synthetic artifacts and owned fake children only."""
from dataclasses import replace
import json
import os
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest

from backend.main import create_app
from backend.orchestrator.workflow import Workflow
from backend.services.current_preview_gate import verify_preview
from backend.services.current_preview_runtime import CurrentPreviewRuntime
from backend.services.simulator_client import LocalSimulatorClient, SimulatorConfig
from tests.test_current_vla_preview import prepared
from tests.test_simulator import FakeProcess


class Launcher:
    def __init__(self):
        self.calls = []
    def preview(self, launcher, root, manifest):
        self.calls.append((launcher, root, manifest))
        self.child = FakeProcess(123)
        return self.child
    def launch(self, *args, **kwargs):
        raise AssertionError('No existing replay process is allowed in this test')


def configured(tmp_path, monkeypatch):
    service, job, result, _ = prepared(tmp_path)
    config = SimulatorConfig(root=service.settings.simulator_root, python=None, launcher=Path(sys.executable),
        sample_id='', data_root=tmp_path/'missing-data', prediction_root=tmp_path/'missing-replay-predictions',
        runtime_dir=tmp_path/'runtime')
    launcher = Launcher()
    runtime = CurrentPreviewRuntime(config, launcher=launcher, monitor=False,
        geometry=service.geometry, clearance=service.clearance)
    service.runtime = runtime
    monkeypatch.setattr('backend.services.current_preview_runtime.verify_preview',
        lambda claim: verify_preview(claim, project=service.settings.project))
    replay = LocalSimulatorClient(config, launcher=launcher, monitor=False)
    app = create_app(workflow=Workflow(service.storage), simulator=replay,
        current_vla_preview=service, preview_runtime=runtime)
    return app, service, job, result, replay, launcher


@pytest.mark.parametrize('missing_replay_launcher', [False, True])
def test_current_preview_admitted_with_replay_configuration_missing(tmp_path, monkeypatch, missing_replay_launcher):
    app, service, job, _, replay, launcher = configured(tmp_path, monkeypatch)
    if missing_replay_launcher:
        replay.config = replace(replay.config, launcher=None)
    with TestClient(app) as api:
        response = api.get('/api/simulator/status')
        assert response.headers['content-type'] == 'application/json; charset=utf-8'
        status = response.json()
        assert not status['existing_replay']['configured']
        assert status['existing_replay']['errors']
        assert status['current_preview']['configured']
        assert status['current_preview']['configuration_errors'] == []
        assert status['configured'] == (not missing_replay_launcher)  # Legacy semantics retained.
        assert not status['can_run_sample']
        if missing_replay_launcher:
            assert api.post('/api/simulator/start', json={}).status_code == 503
        replay.state = 'READY'  # Simulated existing runtime readiness, never a launch.
        replay.simulator = FakeProcess(456)
        assert api.post('/api/simulator/run-sample', json={}).status_code == 503
        assert not launcher.calls
        replay.simulator.stop();replay.simulator=None
        replay.state = 'STOPPED'
        response = api.post('/api/simulator/preview-current-vla', json={'job_id':str(job.id)})
        assert response.status_code == 202, response.text
        assert response.json()['current_preview']['configured']
        assert response.json()['current_preview']['state'] == 'STARTING'
        assert len(launcher.calls) == 1
        manifest = launcher.calls[0][2]
        assert 'missing-replay-predictions' not in json.dumps(manifest)
        assert service.runtime.latest['artifact_id'] == str(job.vla_prediction.artifact_id)
    assert launcher.child.stopped and service.runtime.lease is None


@pytest.mark.parametrize('invalid,code,status', [
    ('launcher','CURRENT_PREVIEW_LAUNCHER_NOT_CONFIGURED',503),
    ('asset','CURRENT_PREVIEW_ASSET_MISSING',503),
    ('audit','PREVIEW_POLICY_NOT_READY',409),
    ('job','CURRENT_PREVIEW_ARTIFACT_INVALID',409),
    ('binding','CURRENT_PREVIEW_ARTIFACT_INVALID',409),
    ('claim','CURRENT_PREVIEW_ARTIFACT_INVALID',409),
])
def test_current_preview_rejections_are_typed_and_never_launch(tmp_path, monkeypatch, invalid, code, status):
    app, service, job, result, _, launcher = configured(tmp_path, monkeypatch)
    if invalid == 'launcher':service.runtime.config = replace(service.runtime.config, launcher=None)
    elif invalid == 'asset':(service.settings.simulator_root/'ATU01035_welding_tool.usd').unlink()
    elif invalid == 'audit':service.clearance.write_text('{}')
    elif invalid == 'job':job.vla_prediction=None;service.storage.save_job(job)
    elif invalid == 'binding':service.storage.artifact_path('native_context',result.artifact_id,'.vla.json').write_text('{}')
    elif invalid == 'claim':
        def invalid_claim(_claim):raise ValueError('tampered fixture')
        monkeypatch.setattr('backend.services.current_preview_runtime.verify_preview', invalid_claim)
    body = {'artifact_id':str(result.artifact_id)} if invalid == 'binding' else {'job_id':str(job.id)}
    with TestClient(app) as api:
        response = api.post('/api/simulator/preview-current-vla', json=body)
        assert response.status_code == status, response.text
        assert response.json()['code'] == code
    assert not launcher.calls and service.runtime.session is None and service.runtime.lease is None


@pytest.mark.parametrize('bom',[False,True])
def test_root_dotenv_is_utf8_source_and_does_not_export_secrets(tmp_path, monkeypatch, bom):
    for key in list(os.environ):
        if key.startswith('WELD_SIM_'):monkeypatch.delenv(key)
    env = tmp_path/'.env'
    root = tmp_path/'2026경남AISW경진대회'/'simulator'
    data = tmp_path/'용접로봇데이터'/'42.용접로봇 행동 생성 데이터'/'3.개방데이터'
    env.write_text(f'WELD_SIM_ROOT={root.as_posix()}\nWELD_SIM_LAUNCHER=D:/isaacsim/python.bat\n'
        f'WELD_SIM_DATA_ROOT={data.as_posix()}\nOPENAI_API_KEY=offline-placeholder\n',encoding='utf-8-sig' if bom else 'utf-8')
    before = dict(os.environ)
    config = SimulatorConfig.from_env(env)
    assert config.root == root.resolve() and config.data_root == data.resolve()
    assert config.launcher == Path('D:/isaacsim/python.bat').resolve()
    assert dict(os.environ) == before
    # Package settings use the same UTF-8 backend source, with a current dataset binding.
    import backend.services.simulator_prediction_package as package_module
    inputs=tmp_path/'inputs.json';inputs.write_text(json.dumps({'dataset_root':str(data)},ensure_ascii=False),encoding='utf-8')
    with env.open('a',encoding='utf-8') as stream:stream.write(f'WELD_GUIDED_VLA_INPUTS={inputs.as_posix()}\n')
    monkeypatch.delenv('WELD_GUIDED_VLA_INPUTS',raising=False)
    monkeypatch.setattr(package_module,'PROJECT',tmp_path)
    settings=package_module.PackageSettings.from_env()
    assert settings.simulator_root==root.resolve() and settings.dataset_root==data.resolve()
    override = tmp_path/'명시 설정'/'python.exe'
    monkeypatch.setenv('WELD_SIM_LAUNCHER',str(override))
    assert SimulatorConfig.from_env(env).launcher==override.resolve()


def test_invalid_dotenv_encoding_fails_closed(tmp_path):
    env=tmp_path/'.env';env.write_bytes(b'WELD_SIM_ROOT=\xff\xfe')
    assert SimulatorConfig.from_env(env).configuration_error == 'Simulator root .env must be readable UTF-8.'


def test_status_preserves_korean_path_bytes(tmp_path, monkeypatch):
    app, service, _, _, replay, launcher = configured(tmp_path, monkeypatch)
    root=tmp_path/'2026경남AISW경진대회'/'simulator'
    replay.config=replace(replay.config,root=root,prediction_root=tmp_path/'용접로봇데이터'/'3.개방데이터')
    with TestClient(app) as api:
        response=api.get('/api/simulator/status')
        assert response.headers['content-type']=='application/json; charset=utf-8'
        assert '2026경남AISW경진대회'.encode('utf-8') in response.content
        assert '3.개방데이터'.encode('utf-8') in response.content
        assert 'ê²½' not in response.text
        assert response.json()['current_preview']['configured']
    assert not launcher.calls
