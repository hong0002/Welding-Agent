"""Fake transport only. No SSH processes, resident workers or model calls."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from backend.model_clients.gpt2_retrieval_diagnostics import RetrievalDiagnostics

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def native_client():
    path = ROOT.parent/'vlm_project2/retrieval_client.py'
    spec = importlib.util.spec_from_file_location('offline_retrieval_client', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    # Compile real source without writing bytecode into the read-only sibling.
    exec(compile(path.read_text(encoding='utf-8'),str(path),'exec'),module.__dict__)
    return module


def fake_popen(monkeypatch, *, code=0, stdout='{}', stderr='', timeout=False):
    class FakeProcess:
        returncode = code
        def __init__(self, *args, **kwargs): self.args = args[0]
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def communicate(self, *args, **kwargs):
            if timeout: raise subprocess.TimeoutExpired('ssh', 1)
            return stdout, stderr
        def kill(self): pass
        def wait(self): return code
        def poll(self): return code
    monkeypatch.setattr(subprocess, 'Popen', FakeProcess)


@pytest.mark.parametrize('code,stdout,stderr,phase,category', [
    (255, '', 'Could not resolve hostname invalid: credential-value', 'SSH_CONFIG', 'SSH_HOSTNAME_UNRESOLVED'),
    (255, '', 'Permission denied (publickey). credential-value', 'SSH_CONNECT', 'SSH_AUTH_FAILED'),
    (1, '', 'No module named service.action_rpc credential-value', 'REMOTE_PYTHON', 'REMOTE_MODULE_MISSING'),
    (0, 'raw prompt credential-value', '', 'RESPONSE_PARSE', 'SSH_TRANSPORT_COMPLETED'),
    (1, json.dumps({'error':'Resident startup failed (exit=1); see /sensitive/path credential-value','type':'RuntimeError'}), '', 'REMOTE_SERVICE', 'SSH_NONZERO_EXIT'),
])
def test_actual_native_transport_and_parser_observed_safely(tmp_path, monkeypatch, native_client, code, stdout, stderr, phase, category):
    fake_popen(monkeypatch, code=code, stdout=stdout, stderr=stderr)
    path = tmp_path/'diagnostics.json'
    with RetrievalDiagnostics(ROOT.parent, path) as diagnostics:
        with pytest.raises(RuntimeError):
            native_client.retrieve_actions(native_client.RetrievalConfig('configured-host','/root','/python'), {'sample_id':'query'})
    report = json.loads(path.read_text())
    assert report['ssh_calls'] == 1 and report['subprocess_exit_code'] == code
    assert report['failure_stage'] == phase and report['ssh_stderr_category'] == category
    assert report['exception_class'] == 'RuntimeError' and report['timeout'] is False
    assert 'credential-value' not in path.read_text() and '/sensitive' not in path.read_text()
    if phase == 'REMOTE_SERVICE':
        assert report['remote_reason_code'] == 'NATIVE_RESIDENT_STARTUP_FAILED' and report['resident_exit_code'] == 1


def test_timeout_is_not_guessed_as_connection_failure(tmp_path, monkeypatch, native_client):
    fake_popen(monkeypatch, timeout=True)
    path = tmp_path/'diagnostics.json'
    with RetrievalDiagnostics(ROOT.parent, path):
        with pytest.raises(subprocess.TimeoutExpired):
            native_client.retrieve_actions(native_client.RetrievalConfig('host','/root','/python'), {'sample_id':'query'})
    report = json.loads(path.read_text())
    assert report['timeout'] and report['failure_stage'] == 'UNKNOWN' and report['ssh_calls'] == 1
    assert report['response_parse_stage'] == 'NOT_RUN' and 'subprocess_exit_code' not in report


def test_success_restores_instrumentation_and_response_exactly(tmp_path, monkeypatch, native_client):
    expected = {'index_split':'train','results':[{'sample_id':'reference'}]}
    fake_popen(monkeypatch, stdout=json.dumps(expected)+'\nnon-json native banner')
    old_profile, old_trace = sys.getprofile(), sys.gettrace()
    with RetrievalDiagnostics(ROOT.parent, tmp_path/'diagnostics.json') as diagnostics:
        result = native_client.retrieve_actions(native_client.RetrievalConfig('host','/root','/python'), {'sample_id':'query'})
    assert result == expected and diagnostics.report['failure_stage'] is None
    assert diagnostics.report['response_parse_stage'] == 'JSON_OBJECT'
    assert diagnostics.report['remote_command_stage'] == 'RESPONSE_RECEIVED'
    assert 'exception_class' not in diagnostics.report
    assert sys.getprofile() is old_profile and sys.gettrace() is old_trace
