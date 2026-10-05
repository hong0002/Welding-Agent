import sys as _release_sys
from pathlib import Path as _ReleasePath
_release_sys.path.insert(0, str(_ReleasePath(__file__).resolve().parents[1]))
from backend.services.project_paths import native_parent
"""Explicit operator migration: replace only the authoritative native URDF block."""
from pathlib import Path
import hashlib
import json
import shutil


def main():
    project = Path(__file__).resolve().parents[1]
    root = native_parent(project) / 'simulator_final'
    target = root / 'run_rb10_trajectory_with_ATU01035.py'
    original = target.read_bytes()
    text = original.decode('utf-8')
    start = text.index('    status, config = omni.kit.commands.execute(')
    end = text.index('    stage = omni.usd.get_context().get_stage()', start)
    block = '''    from urdf_import_compat import import_urdf_isaac61
    robot_path = import_urdf_isaac61(
        URDF_PATH, None,
        dict(merge_fixed_joints=False, convex_decomp=False,
             import_inertia_tensor=True, fix_base=True,
             distance_scale=1.0, make_default_prim=False),
    )

'''
    if text[start:end].count('URDFCreateImportConfig') != 2 or text[start:end].count('URDFParseAndImportFile') != 1:
        raise RuntimeError('Native URDF block differs; refusing to modify other code')
    backup = project / '.cache/simulator-final-audit/urdf-compat-source-backup'
    backup.mkdir(parents=True, exist_ok=True)
    saved = backup / target.name
    if saved.exists() and saved.read_bytes() != original:
        raise RuntimeError('Native source backup already exists for different content')
    saved.write_bytes(original)
    updated = text[:start] + block + text[end:]
    target.write_bytes(updated.encode('utf-8'))
    shutil.copyfile(project / 'backend/urdf_import_compat.py', root / 'urdf_import_compat.py')
    report = dict(source=str(target), original_sha256=hashlib.sha256(original).hexdigest(),
                  updated_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                  changed_block='URDF import only', outside_block_unchanged=True)
    (backup / 'migration.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
