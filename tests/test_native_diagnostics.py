"""Only small local stub children. No native source imports, SDK, network or model calls."""
import json
import subprocess
import sys

import pytest

from backend.model_clients.native_process import run_native
from backend.model_clients.native_watchdog import NativeWatchdog, WatchdogPolicy
from backend.model_clients.native_diagnostics import NativeDiagnostics


def records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_gpt2_boundary_milestones_are_allowlisted_no_payload(tmp_path):
    path=tmp_path/'trace.jsonl';trace=NativeDiagnostics(path)
    for line in ('[GPT2_RETRIEVAL] ssh_started','[GPT2_STAGE] start=rough','[GPT2_STAGE] completed=rough',
                 '[GPT2_STAGE] start=corners','[GPT2_STAGE] completed=corners',
                 '[GPT2_STAGE] start=rough private-secret','[GPT2_PROCESS_FAILED] exception=ValueError'):
        trace.output(line)
    rows=records(path)
    assert [v['stage'] for v in rows if v['event']=='gpt2_stage_start']==['rough','corners']
    assert 'private-secret' not in path.with_suffix('.native.log').read_text(encoding='utf-8')


def test_utf8_launcher_unbuffered_flag_is_observed_after_x_option(tmp_path):
    script=tmp_path/'stub.py';script.write_text('print("[GPT2_STAGE] start=rough")\n',encoding='utf-8')
    log=tmp_path/'trace.jsonl'
    code,_=run_native([sys.executable,'-B','-X','utf8','-u',str(script)],cwd=tmp_path,timeout=5,diagnostic_path=log)
    assert code==0 and next(r for r in records(log) if r['event']=='process_started')['unbuffered_cli'] is True


@pytest.mark.parametrize('preserve', [False, True])
def test_backend_owned_env_key_opt_in_never_logs_value(tmp_path, monkeypatch, preserve):
    monkeypatch.setenv('OPENAI_API_KEY', 'offline-key-sentinel')
    script = tmp_path / 'key_presence_stub.py'
    script.write_text("import os,sys\n"
                      "sys.exit(0 if bool(os.getenv('OPENAI_API_KEY')) == (sys.argv[1] == 'yes') else 2)\n",
                      encoding='utf-8')
    log = tmp_path / 'presence.jsonl'
    code, _ = run_native([sys.executable, '-B', str(script), 'yes' if preserve else 'no'],
                         cwd=tmp_path, timeout=5, diagnostic_path=log, preserve_openai_api_key=preserve)
    assert code == 0
    assert next(r for r in records(log) if r['event'] == 'process_started')['inherited_openai_api_key_removed'] is not preserve
    assert 'offline-key-sentinel' not in log.read_text(encoding='utf-8')
    assert 'offline-key-sentinel' not in log.with_suffix('.native.log').read_text(encoding='utf-8')


def test_allowlisted_milestones_artifacts_and_exit_without_raw_stdout(tmp_path):
    script = tmp_path / "stub.py"
    output = tmp_path / "output"
    session = output / "20260930_000001_SAMPLE"
    stale = output / "20260930_000000_SAMPLE/iteration_001"
    stale.mkdir(parents=True)
    (stale / "F_prediction.png").write_bytes(b"stale")
    script.write_text("""from pathlib import Path
import sys
p=Path(sys.argv[1]);d=p/'iteration_001';d.mkdir(parents=True)
print('[RETRIEVE] sample=SAMPLE',flush=True)
print('[RETRIEVED] REF',flush=True)
(p/'retrieval.json').write_text('{}')
print('raw payload private-test-secret',flush=True)
sys.stderr.write('hidden reasoning private-test-secret\\n')
for camera in ('F','R','S4'):
 print(f'[GPT] iteration=1 camera={camera} examples=3',flush=True)
 (d/f'{camera}_prediction.png').write_bytes(b'stub')
(d/'result.json').write_text('{}')
print('[RESULT] mean IoU=0.1000, mean Dice=0.2000',flush=True)
print('[VIEW] '+str(d/'comparison_all.jpg'),flush=True)
""", encoding="utf-8")
    log = tmp_path / "diagnostics/run.jsonl"
    code, views = run_native([sys.executable, "-B", "-u", str(script), str(session)],
                            cwd=tmp_path, timeout=5, diagnostic_path=log, output_root=output, sample_id="SAMPLE")
    rows = records(log)
    assert code == 0 and len(views) == 1
    assert [r["view"] for r in rows if r["event"] == "view_started"] == ["F", "R", "S4"]
    assert {r["event"] for r in rows} >= {"process_started", "gate_released", "retrieval_completed", "process_exited", "cleanup_completed"}
    seen = [r for r in rows if r["event"] == "artifact_observed"]
    assert {r["artifact"] for r in seen} >= {"retrieval.json", "iteration_001/F_prediction.png", "iteration_001/R_prediction.png", "iteration_001/S4_prediction.png", "iteration_001/result.json"}
    assert all(r["session_id"] == session.name for r in seen)
    text = log.read_text(encoding="utf-8")
    assert "private-test-secret" not in text and "hidden reasoning" not in text and "raw payload" not in text
    elapsed = [r["elapsed_seconds"] for r in rows]
    assert elapsed == sorted(elapsed)
    assert rows[-1]["supervisor_returncode"] == 0
    native = log.with_suffix(".native.log").read_text(encoding="utf-8")
    assert "private-test-secret" not in native and "raw payload" not in native
    assert all(marker in native for marker in ("[RETRIEVE]", "[RETRIEVED]", "camera=F", "camera=R", "camera=S4", "[RESULT]", "[PROCESS_EXIT] code=0"))
    assert next(r for r in rows if r["event"] == "watchdog_policy")["per_view"] == 240


def test_timeout_preserves_last_observed_view_and_cleanup(tmp_path):
    script = tmp_path / "stub.py"
    script.write_text("import time\nprint('[GPT] iteration=1 camera=R examples=3',flush=True)\ntime.sleep(30)\n")
    log = tmp_path / "timeout.jsonl"
    with pytest.raises(subprocess.TimeoutExpired):
        run_native([sys.executable, "-B", "-u", str(script)], cwd=tmp_path, timeout=1,
                   diagnostic_path=log)
    rows = records(log)
    assert next(r for r in rows if r["event"] == "timeout")["last_observed_phase"] == "view_R"
    assert rows[-1]["event"] == "cleanup_completed" and rows[-1]["termination_reason"] == "timeout"
    # Windows kill-on-close Job Objects may report 0. It is not a successful native exit.
    assert isinstance(rows[-1]["supervisor_returncode"], int)
    assert not any(r["event"] == "process_exited" for r in rows)


def test_heavy_unrecognized_stdout_is_drained_without_persisting_payload(tmp_path):
    script = tmp_path / "stub.py"
    script.write_text("print('private-payload-' * 40000)\nprint('[GPT] iteration=1 camera=F examples=3')\n")
    log = tmp_path / "bounded.jsonl"
    code, _ = run_native([sys.executable, "-B", "-u", str(script)], cwd=tmp_path, timeout=5,
                         diagnostic_path=log)
    assert code == 0 and log.stat().st_size < 4000
    assert "private-payload" not in log.read_text(encoding="utf-8")
    assert any(r["event"] == "view_started" for r in records(log))


def test_parity_watchdog_reset_points_and_overall_cap():
    now = [0.0]
    watchdog = NativeWatchdog(900, clock=lambda: now[0])
    assert watchdog.remaining() == (60, "setup")
    now[0] = 20
    watchdog.output("[RETRIEVE] sample=SAMPLE, top_k=3")
    assert watchdog.remaining() == (120, "retrieval")
    now[0] = 40
    watchdog.output("[RETRIEVED] REF")
    assert watchdog.remaining() == (100, "retrieval")
    for stamp, camera in ((100, "F"), (330, "R"), (560, "S4")):
        now[0] = stamp
        watchdog.output(f"[GPT] iteration=1 camera={camera} examples=3")
        assert watchdog.remaining() == (240, "view_" + camera)
    now[0] = 799
    watchdog.output("[RESULT] mean IoU=0.1000, mean Dice=0.2000")
    assert watchdog.remaining() == (1, "view_S4")
    now[0] = 801
    assert watchdog.remaining() == (-1, "view_S4")
    watchdog.output("[GPT] iteration=2 camera=F examples=3")
    assert watchdog.remaining() == (99, "overall")
    now[0] = 901
    assert watchdog.remaining() == (-1, "overall")


@pytest.mark.parametrize("marker,stage", [("", "setup"), ("[RETRIEVE] sample=SAMPLE, top_k=3", "retrieval"),
                                        ("[GPT] iteration=1 camera=R examples=3", "view_R")])
def test_stage_watchdog_kills_stub_without_retry(tmp_path, marker, stage):
    script = tmp_path / "stage_stub.py"
    script.write_text("from pathlib import Path\nimport time\n"
                      "with Path('starts').open('a') as f: f.write('once\\n')\n"
                      f"print({marker!r},flush=True)\ntime.sleep(30)\n", encoding="utf-8")
    log = tmp_path / "stage.jsonl"
    with pytest.raises(subprocess.TimeoutExpired):
        run_native([sys.executable, "-B", "-u", str(script)], cwd=tmp_path, timeout=10,
                   diagnostic_path=log, watchdog_policy=WatchdogPolicy(setup=1, retrieval=1, model_stage=1))
    rows = records(log)
    expired = next(r for r in rows if r["event"] == "timeout")
    assert expired["watchdog_stage"] == stage
    assert expired["elapsed_seconds"] < 5
    assert (tmp_path / "starts").read_text().splitlines() == ["once"]
    assert rows[-1]["termination_reason"] == "timeout" and not rows[-1]["stdout_reader_alive"]


def test_sanitized_error_messages_and_log_are_exclusive(tmp_path):
    log = tmp_path / "redaction.jsonl"
    trace = NativeDiagnostics(log)
    trace.output('[GPT] iteration=1 camera=R examples=3')
    trace.output('openai.APITimeoutError: Request timed out. API_KEY=private-secret')
    trace.output('openai.AuthenticationError: Error code: 401 - {"prompt": "private-secret"}')
    trace.output('RuntimeError: full sensitive prompt private-secret')
    trace.output('[RETRIEVED] sk-private-secret raw request')
    trace.output('Authorization: Bearer private-secret')
    native = log.with_suffix('.native.log').read_text(encoding='utf-8')
    assert 'APITimeoutError: Request timed out.' in native
    assert 'AuthenticationError: HTTP 401; response body omitted' in native
    assert 'private-secret' not in native and 'private-secret' not in log.read_text()
    assert next(r for r in records(log) if r.get('error_class') == 'APITimeoutError')['phase'] == 'view_R'
    with pytest.raises(FileExistsError):
        NativeDiagnostics(log)


def test_rough_stage_markers_and_artifact_availability_never_read_markdown(tmp_path):
    output = tmp_path / "rough"
    log = tmp_path / "rough.jsonl"
    trace = NativeDiagnostics(log, output_root=output, sample_id="SAMPLE")
    session = output / "20260930_000001_SAMPLE"
    (session / "iteration_001").mkdir(parents=True)
    for name in ("retrieval.json", "query_rough_action.json", "refiner.json", "query_masks.jpg",
                 "iteration_001/plan.json", "iteration_001/cot_ko.md", "iteration_001/vla_prompt.md",
                 "iteration_001/rough_trajectory_overlay.jpg"):
        (session / name).write_text("private-reasoning-never-read", encoding="utf-8")
    trace.output("[REFINE] sample=SAMPLE, prompt=refiner-v1")
    trace.output("[RETRIEVE] image+text+mask sample=SAMPLE")
    trace.output("[RETRIEVED] REF_1, REF_2")
    trace.output("[GPT] iteration=1, references=2, prompt=planner-v1")
    for tag, name in (("VIEW", "rough_trajectory_overlay.jpg"), ("COT", "cot_ko.md"), ("VLA", "vla_prompt.md")):
        trace.output(f"[{tag}] {session / 'iteration_001' / name}")
    trace.artifacts()
    rows = records(log)
    assert [r["event"] for r in rows[:4]] == ["instruction_refinement_started", "retrieval_started", "retrieval_completed", "planning_started"]
    assert len([r for r in rows if r["event"] == "artifact_observed"]) == 8
    native = log.with_suffix(".native.log").read_text(encoding="utf-8")
    assert "[GPT] iteration=1, references=2, prompt=planner-v1" in native
    assert "[VLA] 20260930_000001_SAMPLE/iteration_001/vla_prompt.md" in native
    assert "private-reasoning-never-read" not in native + log.read_text(encoding="utf-8")
