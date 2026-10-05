import sys as _release_sys
from pathlib import Path as _ReleasePath
_release_sys.path.insert(0, str(_ReleasePath(__file__).resolve().parents[1]))
from backend.services.project_paths import native_parent
"""Explicit authorized native capture-only migration; keep the rest byte-identical."""
import hashlib
import json
from pathlib import Path
import shutil


def main():
    project=Path(__file__).resolve().parents[1];root=native_parent(project)/'simulator_final'
    target=root/'run_rb10_trajectory_with_ATU01035.py'
    original=target.read_bytes();source=original.decode('utf-8')
    start=source.index('def capture_frame(label):')
    end=source.index('\n\ndef main():',start)
    block='''def capture_frame(label):
    if args.capture_dir is None:
        return
    from viewport_capture_compat import capture_native_frame
    path=(args.capture_dir/(label+'.png')).resolve()
    capture_native_frame(simulation_app,path)
    print(f'[CAPTURE] {path}',flush=True)
'''
    if 'capture_viewport_to_file' not in source[start:end] or 'deadline=time.perf_counter()+20.' not in source[start:end]:
        raise RuntimeError('Native capture block differs; refusing unrelated edits')
    backup=project/'.cache/simulator-final-audit/capture-compat-source-backup';backup.mkdir(parents=True,exist_ok=True)
    saved=backup/target.name
    if saved.exists() and saved.read_bytes()!=original:raise RuntimeError('Conflicting migration backup')
    saved.write_bytes(original)
    target.write_bytes((source[:start]+block+source[end:]).encode('utf-8'))
    shutil.copyfile(project/'backend/viewport_capture_compat.py',root/'viewport_capture_compat.py')
    report=dict(original_sha256=hashlib.sha256(original).hexdigest(),updated_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                changed_block='capture_frame only',outside_block_unchanged=True)
    (backup/'migration.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':main()
