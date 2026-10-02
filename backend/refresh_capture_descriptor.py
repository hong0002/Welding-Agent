"""Explicit offline rebind of the audited capture-bug release, without solving IK.

No process/network/Isaac imports. Old descriptors and native packages stay immutable.
Status polling and web launch never perform this migration automatically.
"""
import argparse
import copy
import json
from pathlib import Path
from uuid import UUID, uuid4

from backend.services.current_preview_gate import read, sha, verify_preview
from backend.services.simulator2_gate import OWNED_CODE, verify
from backend.services.storage import LocalStorage

# Exact release audited before this fix; do not accept arbitrary stale code.
PRE_CAPTURE_OWNED_CODE = {
    'backend/current_vla_isaac_preview.py':'429dc25b26157603f860dd4bdaff3f0cf04f0bfbfa331bf0bc2811c5df404582',
    'backend/services/current_preview_gate.py':'e06301545a0a0454d9782ddb78bb9ade20cb52913f0887db37d8341a1d0efd90',
    'backend/services/simulator2_gate.py':'44f24b65379ee4bfd7feb7ea7060026e9fe456184c6ef0484b58ee30adc3b01c',
    'backend/services/simulator2_client.py':'d87171ec995059b077a18896f82eac1c0cf704cade4ca30d495bc09f896f59d2',
    'backend/services/simulator2_contract.py':'b68c0f7139f7c04103cf453d218a4323fe5f59761e74fd7e0f4a15c19f853f40',
    'backend/simulator2_prepare.py':'2301e1428c13f6ff3d44c2249ecd8e85d14aa5b90d19a6ac2b9e52d5c794a801',
}


def refresh(artifact_id, *, kind='robot', project=None):
    artifact_id = str(UUID(str(artifact_id)))
    if kind not in {'robot','path'}:
        raise ValueError('Invalid preview kind')
    project = (project or Path(__file__).resolve().parents[1]).resolve()
    cached = project/'.cache/simulator2/readiness'/artifact_id/(kind+'.json')
    old = read(cached)
    path = Path(old['path']).resolve()
    root = project/'.cache/simulator/current-previews/packages'
    if (path.parent.parent!=root or path.name!='preview.json' or
            str(UUID(path.parent.name))!=path.parent.name or sha(path)!=old['sha256']):
        raise ValueError('Invalid immutable descriptor claim')
    d = read(path)
    if (d['schema_version']!='current-vla-preview-v3' or d['artifact_id']!=artifact_id or
            d['kind']!=kind or d['preview_id']!=path.parent.name):
        raise ValueError('Wrong dataset-v2 descriptor')
    current = {name:sha(Path(__file__).resolve().parents[1]/name) for name in OWNED_CODE}
    if d['owned_code']==current:
        verify_preview(old, project=project)
        return old
    if d['owned_code']!=PRE_CAPTURE_OWNED_CODE:
        raise ValueError('Stale renderer is not the audited pre-capture release')
    updated = copy.deepcopy(d)
    updated['owned_code'] = current
    # Verify every source, approval, prediction, native solution and external asset
    # using the unchanged normal gate. Only the known owned renderer release differs.
    verify(updated, path, project)
    preview_id = str(uuid4())
    updated.update(preview_id=preview_id, capture_renderer_refresh=dict(
        previous_descriptor=old, reason='SIMULATOR2_CAPTURE_NONFATAL_FIX', native_recomputed=False))
    target = root/preview_id/'preview.json'
    target.parent.mkdir(parents=True, exist_ok=False)
    LocalStorage._write_json(target,json.dumps(updated,indent=2,allow_nan=False))
    claim = dict(path=str(target),sha256=sha(target))
    verify_preview(claim,project=project)
    LocalStorage._write_json(cached,json.dumps(claim))
    return claim


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-id',required=True,type=UUID)
    parser.add_argument('--kind',choices=('robot','path'),default='robot')
    args=parser.parse_args()
    try:
        claim=refresh(args.artifact_id,kind=args.kind)
        d=read(claim['path'])
        print(json.dumps(dict(status='CAPTURE_RENDERER_REBOUND',preview_id=d['preview_id'],
            package_id=d['package_id'],artifact_id=d['artifact_id'],sample_id=d['sample_id'],
            source_point_count=d['source_point_count'],playback_point_count=d['playback_point_count'],
            native_recomputed=False,isaac_launched=False)))
    except (ValueError,OSError,KeyError,TypeError):
        raise SystemExit('CAPTURE_RENDERER_REBIND_REJECTED: immutable evidence or audited release differs')
