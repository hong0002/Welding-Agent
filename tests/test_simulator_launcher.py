import io
import json
import os
from pathlib import Path
import sys
import threading

import pytest

from backend.services.simulator_process import ProcessLauncher, batch_command
from backend.services.simulator_diagnostics import read_import_check, write_import_check
from backend.services.simulator_client import SimulatorConfig
from backend.simulator_smoke import check_environment


def test_batch_command_has_fixed_cmd_and_preserves_korean_space_parentheses(tmp_path):
    launcher = tmp_path / "한글 경로 (Isaac)" / "python.bat"
    runner = tmp_path / "작업 공간" / "simulator_runner.py"
    command = batch_command(launcher, runner, system_root=Path("C:/Windows"))
    assert '/D /V:OFF /S /C ""' in command
    assert command.endswith(f'"{launcher}" -B -u "{runner}""')
    assert 'cmd.exe' in command and '한글 경로 (Isaac)' in command


@pytest.mark.parametrize("bad", ['x%PATH%', 'x&whoami', 'x!x', 'x^x', 'x|x', 'x"x', 'x\nx', 'x>x'])
def test_batch_control_characters_fail_closed(tmp_path, bad):
    with pytest.raises(ValueError, match="control characters"):
        batch_command(tmp_path / bad / "python.bat", tmp_path / "runner.py")


@pytest.mark.skipif(os.name != "nt", reason="Windows batch semantics")
def test_real_batch_stub_preserves_environment_and_unicode_arguments(tmp_path, monkeypatch):
    # A lightweight batch stand-in, not D:/isaacsim/python.bat or any real simulator.
    root = tmp_path / "한글 경로 (standalone)"; root.mkdir()
    batch = root / "python.bat"
    monkeypatch.setenv("WELD_STUB_PYTHON", sys.executable)
    batch.write_text('@echo off\nset WELD_STUB_ENV=initialized\ncall "%WELD_STUB_PYTHON%" %*\nexit /b %errorlevel%\n', encoding="ascii")
    script = root / "run_welding_sample.py"
    script.write_text("import os,sys,json\nassert sys.flags.utf8_mode == 1\nprint(json.dumps([os.environ['WELD_STUB_ENV'],sys.argv[1:]],ensure_ascii=True),flush=True)\n", encoding="utf-8")
    arguments = ["--samples-dir", "D:/한글 경로/03(3mm)/x&y%z!q", "--sample", "L_PR_03_0001"]
    process = ProcessLauncher().launch(batch, root, script.name, arguments)
    output, done = [], threading.Event()
    def read():
        output.extend(process.stdout.readlines()); done.set()
    reader = threading.Thread(target=read, daemon=True); reader.start()
    try:
        assert done.wait(10), ''.join(output)
        assert process.process.wait(timeout=3) == 0, ''.join(output)
        assert json.loads(''.join(output).strip()) == ["initialized", arguments]
    finally:
        process.stop(); reader.join(timeout=2); process.stdout.close()


def test_import_check_is_cached_and_invalidated_for_changed_launcher(tmp_path):
    launcher = tmp_path / "python.bat"; launcher.write_text("stub")
    config = SimulatorConfig(tmp_path, None, "sample", tmp_path, tmp_path, tmp_path / "runtime", launcher=launcher)
    assert read_import_check(config)["status"] == "not_run"
    write_import_check(config, {"status": "passed"})
    assert read_import_check(config)["status"] == "passed"
    launcher.write_text("changed launcher")
    os.utime(launcher, ns=(1, 2))
    assert read_import_check(config)["status"] == "not_run"


@pytest.mark.parametrize("passed", [True, False])
def test_import_probe_records_success_or_failure_without_real_isaac(tmp_path, passed):
    for script in ("run_welding_simulator.py", "run_welding_sample.py"):
        (tmp_path / script).write_text("#stub")
    config = SimulatorConfig(tmp_path, Path(sys.executable), "sample", tmp_path, tmp_path, tmp_path.parent / (tmp_path.name + "-runtime"))
    class Probe:
        stdout = io.StringIO('[ISAAC_IMPORT_CHECK] {"status":"passed", "python":"kit.exe"}\n' if passed else 'ModuleNotFoundError\n')
        def poll(self): return 0 if passed else 1
        def stop(self): pass
    class Launcher:
        def probe(self, *_args): return Probe()
    result = check_environment(config, launcher=Launcher())
    assert result["status"] == ("passed" if passed else "failed")
    assert read_import_check(config)["status"] == result["status"]
