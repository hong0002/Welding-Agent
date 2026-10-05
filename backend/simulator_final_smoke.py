"""Explicit one-shot native standalone smoke, fixed existing Guided fixture.

Not invoked by APIs/tests. No retry. An owned native snapshot isolates importer
outputs while running native prepare/main/capture and articulation unchanged.
"""
from pathlib import Path
import hashlib
import json
import os
import shutil
import sys
import threading
import time
from uuid import uuid4


def main():
    project = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project))
    from backend.services.simulator_process import FileLease, ProcessLauncher
    root = project.parent / 'simulator_final'
    out = project / '.cache/simulator-final-audit' / str(uuid4())
    out.mkdir(); native = out / 'native'; native.mkdir()
    sources = {}
    paths = [*root.glob('*.py'), *root.glob('*.usd'),
             root / 'rb10_trajectory_with_ATU01035.usda', *root.glob('rbpodo_description/**/*')]
    for file in paths:
        if not file.is_file() or '__pycache__' in file.parts:
            continue
        relative = file.relative_to(root); target = native / relative
        target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(file, target)
        sources[str(relative)] = hashlib.sha256(file.read_bytes()).hexdigest()
    package = project / '.cache/simulator/prediction-packages/298a9efb-14d2-403e-9ac9-42c887da32bf'
    package_manifest = json.loads((package / 'package.json').read_text(encoding='utf-8'))
    h5 = Path(package_manifest['h5'])
    prediction = out / 'prediction/B_PR_03_0004'; prediction.mkdir(parents=True)
    for name in ('trajectory.npz', 'metadata.json'):
        shutil.copyfile(package / 'predictions/B_PR_03_0004' / name, prediction / name)
    options = dict(native=str(native), h5=str(h5), prediction=str(prediction), output=str(out),
                   source_npz_sha256=hashlib.sha256((prediction / 'trajectory.npz').read_bytes()).hexdigest())
    from backend.simulator_final_experience import build_experience
    options['experience'] = str(build_experience(Path('D:/isaacsim'), out/'experience'))
    (out / 'manifest.json').write_text(json.dumps(options | dict(source_hashes=sources,
        sample_id='B_PR_03_0004', artifact_id='7bdec2fd-a3dc-478e-b623-ca8ae448f44d',
        launcher='D:/isaacsim/python.bat', model_calls=0), indent=2), encoding='utf-8')
    # The only audit wrapper selects original native functions and CLI flags.
    # It does not implement scene transforms, renderer, IK/FK or timing.
    entry = out / 'run_welding_simulator.py'
    entry.write_text('''import json, os, runpy, sys
from pathlib import Path
p = json.loads(Path(__file__).with_name('manifest.json').read_text(encoding='utf-8'))
native = Path(p['native']); output = Path(p['output'])
sys.path.insert(0, str(native))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]/'backend'))
from simulator_final_experience import bind_experience
bind_experience(Path(p['experience']))
os.environ['WELD_SIM_URDF_OUTPUT_DIR'] = str(output/'urdf')
from run_welding_sample import ExtractedSamples, prepare, sample_index
archive = ExtractedSamples(Path(p['h5']).parent)
solution = prepare(archive, sample_index(archive)['B_PR_03_0004'], output/'prepared',
                   prediction_dir=Path(p['prediction']), layout='stp', prediction_stage='final')
print('[STANDALONE] Native preparation complete', flush=True)
sys.argv = [str(native/'run_rb10_trajectory_with_ATU01035.py'),
 '--solution', str(solution), '--output', str(output/'scene.usda'),
 '--duration-sec', '15', '--camera-distance-scale', '1',
 '--capture-dir', str(output/'captures'), '--no-video', '--headless', '--auto-close']
runpy.run_path(sys.argv[0], run_name='__main__')
''', encoding='utf-8')
    for name in list(os.environ):
        if any(word in name.upper() for word in ('API_KEY', 'SECRET', 'TOKEN')):
            os.environ.pop(name)
    os.environ['PYTHONPATH'] = str(project / '.cache/simulator2/python-deps')
    lease = FileLease(project / '.cache/simulator/owner.lock')
    process = None
    print(json.dumps(dict(phase='START', output=str(out), sample='B_PR_03_0004')), flush=True)
    try:
        process = ProcessLauncher()._launch(Path('D:/isaacsim/python.bat'), native,
            dict(mode='script', script=str(entry), arguments=[]))
        def drain():
            with (out / 'native.log').open('w', encoding='utf-8') as stream:
                for line in process.stdout:
                    stream.write(line); stream.flush()
                    if line.startswith(('[OK]', '[URDF_COMPAT]', '[STANDALONE]', '[ROBOT]', '[INIT]',
                                        '[ATTACH]', '[PLAYBACK]', '[SAVE]', '[CAPTURE]', '[TRACKING]')):
                        print(line.rstrip(), flush=True)
        reader = threading.Thread(target=drain, daemon=True); reader.start()
        deadline = time.monotonic() + 240
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(.5)
        timeout = process.poll() is None
        if timeout:
            process.stop()
        reader.join(10)
        log = (out / 'native.log').read_text(encoding='utf-8')
        captures = sorted(p.name for p in (out / 'captures').glob('*.png'))
        success = (process.poll() == 0 and not timeout and 'Traceback (most recent call last)' not in log
                   and '[PLAYBACK] finished' in log and (out / 'scene.usda').is_file()
                   and (out / 'scene.actual_weld.npz').is_file() and len(captures) == 3)
        result = dict(verdict='STANDALONE_PASS' if success else 'STANDALONE_FAIL',
            exit_code=process.poll(), timeout=timeout, captures=captures,
            external_sources_unchanged=all(hashlib.sha256((root/n).read_bytes()).hexdigest() == h for n,h in sources.items()),
            isaac_launches=1, model_calls=0, output=str(out), integration_started=False)
        (out / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result), flush=True)
    finally:
        if process:
            process.stop()
        lease.close()


if __name__ == '__main__':
    main()
