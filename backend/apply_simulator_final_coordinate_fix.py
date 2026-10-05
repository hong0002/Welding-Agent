"""Explicit minimal native registration migration with source backup/evidence."""
from pathlib import Path
import hashlib
import json
import shutil


def patched_source(source):
    begin=source.index('def principal_basis(points):')
    end=source.index('\n\ndef rigid_fit(',begin)
    source=source[:begin]+'''def principal_basis(points):
    from contact_registration_determinism import canonical_principal_basis
    return canonical_principal_basis(points)
'''+source[end:]
    begin=source.index('def rigid_fit(source, target):')
    end=source.index('\n\ndef register_path(',begin)
    source=source[:begin]+'''def rigid_fit(source, target):
    from contact_registration_determinism import deterministic_rigid_fit
    return deterministic_rigid_fit(source, target)
'''+source[end:]
    source=source.replace('    tree = cKDTree(contact)',
        '    tree = cKDTree(contact)\n    from contact_registration_determinism import deterministic_nearest')
    source=source.replace('tree.query(transformed)','deterministic_nearest(tree, transformed)')
    source=source.replace('tree.query(points @ rotation.T + translation)',
                          'deterministic_nearest(tree, points @ rotation.T + translation)')
    source=source.replace('tree.query(fitted)','deterministic_nearest(tree, fitted)')
    source=source.replace('''                    update, shift = rigid_fit(transformed, contact[indices])
                    rotation, translation = update @ rotation, update @ translation + shift''',
'''                    from contact_registration_determinism import registration_update
                    rotation, translation = registration_update(points, contact[indices], rotation, translation)''')
    old='''                if best is None or score < best[0]:
                    best = score, rotation, translation
    rotation, translation = best[1:]'''
    new='''                from contact_registration_determinism import registration_preference, prefer_registration
                preference_key = registration_preference(points, rotation, translation)
                if prefer_registration(score, preference_key, best):
                    best = score, rotation, translation, preference_key
    rotation, translation = best[1:3]'''
    if source.count(old)!=1:
        raise ValueError('Native registration contract changed')
    return source.replace(old,new)


def main():
    project=Path(__file__).resolve().parents[1]
    root=project.parent/'simulator_final'
    backup=project/'.cache/simulator-final-audit/coordinate-source-backup'
    path=root/'welding_contact_fixture.py'
    before=path.read_text(encoding='utf-8')
    after=patched_source(before)
    backup.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(path,backup/path.name)
    path.write_text(after,encoding='utf-8')
    shutil.copyfile(project/'backend/contact_registration_determinism.py',root/'contact_registration_determinism.py')
    (backup/'migration.json').write_text(json.dumps(dict(
        before_sha256=hashlib.sha256(before.encode()).hexdigest(),
        after_sha256=hashlib.sha256(after.encode()).hexdigest(),
        scope='PCA hemisphere, rank-aware rigid update, contact ties and equivalent-candidate selection; native geometry/objective retained'),indent=2),encoding='utf-8')
    print('COORDINATE_REGISTRATION_MIGRATION_APPLIED')


if __name__=='__main__':main()
