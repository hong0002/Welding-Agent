"""Explicit audited renderer-only upgrade; no models/native math/Isaac.

Source package, native solution and old descriptor stay immutable. Unknown stale
releases are refused. Status polling never performs this operation automatically.
"""
import argparse
import copy
import json
from pathlib import Path
from uuid import UUID, uuid4
from backend.services.current_preview_gate import read, sha, verify_preview
from backend.services.storage import LocalStorage

PRE_UX_OWNED_CODE = {
    "dataset_v2": {
        "backend/current_vla_isaac_preview.py": "c1a0ed889ba9957a2dc846f9aebbdc6a636fcbaf776bbefe265f7c0b0d5e3d76",
        "backend/services/current_preview_gate.py": "3d3e5b473152ad5961b1c82b07a8192b233efc23de648bcc1c619cc5362099f0",
        "backend/services/simulator2_gate.py": "853d8a573d23f7e3f753be73afd64edadb8e2cba51d9d9d52ef27ac371d209dc",
        "backend/services/simulator2_client.py": "2790148986edb273f1c13f911e8a6b46aae7bc2802efceadf392a26f8f9ae602",
        "backend/services/simulator2_contract.py": "b68c0f7139f7c04103cf453d218a4323fe5f59761e74fd7e0f4a15c19f853f40",
        "backend/simulator2_prepare.py": "93dcbcb040f0107c8422c2348224750626245cf523e173c0f881594da47fb1fe",
        "backend/services/preview_capture.py": "e254ea46267233c01b68565486845b3d10cd7a7741ee43ec609bf79ad765919e"
    },
    "dataset_stp": {
        "backend/current_vla_isaac_preview.py": "c1a0ed889ba9957a2dc846f9aebbdc6a636fcbaf776bbefe265f7c0b0d5e3d76",
        "backend/services/current_preview_gate.py": "3d3e5b473152ad5961b1c82b07a8192b233efc23de648bcc1c619cc5362099f0",
        "backend/services/simulator2_gate.py": "853d8a573d23f7e3f753be73afd64edadb8e2cba51d9d9d52ef27ac371d209dc",
        "backend/services/simulator2_client.py": "2790148986edb273f1c13f911e8a6b46aae7bc2802efceadf392a26f8f9ae602",
        "backend/services/simulator2_contract.py": "b68c0f7139f7c04103cf453d218a4323fe5f59761e74fd7e0f4a15c19f853f40",
        "backend/simulator2_prepare.py": "93dcbcb040f0107c8422c2348224750626245cf523e173c0f881594da47fb1fe",
        "backend/services/preview_capture.py": "e254ea46267233c01b68565486845b3d10cd7a7741ee43ec609bf79ad765919e",
        "backend/services/simulator_stp_gate.py": "01c60faa7d943f297f3eaefca4dee59d1e744be5fc1535975803faf4bf1756a1",
        "backend/services/simulator_stp_contract.py": "348c72b49e24ea20f8cf47991b4f8a1fe551b0829bfccd9c2a3e799c1fe67d42",
        "backend/services/simulator_stp_client.py": "9eb9c3e4464972b1142070d91e1c762fc24beb8723d20f8c0c61255d848c609f",
        "backend/simulator_stp_prepare.py": "e73ba4a12028c545d930c04acc072b70f15e9f75e6913456af30522e90fd7394",
        "backend/services/preview_environment.py": "9860ea7fd1b7c5396494d1335f87e56750d3fdde8c3225f46321e3e059b7b411"
    }
}


def refresh(artifact_id, *, backend='dataset_stp', kind='robot', project=None):
    artifact_id = str(UUID(str(artifact_id)))
    if backend not in PRE_UX_OWNED_CODE or kind not in {'path','robot'}:
        raise ValueError('Unsupported renderer upgrade')
    project = (project or Path(__file__).resolve().parents[1]).resolve()
    namespace = 'simulator-stp' if backend=='dataset_stp' else 'simulator2'
    cached = project/'.cache'/namespace/'readiness'/artifact_id/(kind+'.json')
    old = read(cached); path = Path(old['path']).resolve()
    root = project/'.cache/simulator/current-previews/packages'
    if (path.parent.parent!=root or path.name!='preview.json' or
            str(UUID(path.parent.name))!=path.parent.name or sha(path)!=old['sha256']):
        raise ValueError('Invalid immutable descriptor')
    d=read(path)
    if d['backend']!=backend or d['artifact_id']!=artifact_id or d['kind']!=kind or d['preview_id']!=path.parent.name:
        raise ValueError('Wrong current preview identity')
    if backend=='dataset_stp':
        from backend.services.simulator_stp_gate import OWNED_CODE, verify
    else:
        from backend.services.simulator2_gate import OWNED_CODE, verify
    code_root=Path(__file__).resolve().parents[1]
    current={name:sha(code_root/name) for name in OWNED_CODE}
    if d['owned_code']==current:
        verify_preview(old,project=project)
        return old
    if d['owned_code']!=PRE_UX_OWNED_CODE[backend]:
        raise ValueError('Unknown stale renderer release')
    updated=copy.deepcopy(d);updated['owned_code']=current
    # Unchanged normal gate verifies ALL native/source/approval/asset evidence.
    # Only the exact allowlisted owned-code release is replaced in memory.
    verify(updated,path,project)
    updated.update(preview_id=str(uuid4()),ux_renderer_refresh=dict(
        previous_descriptor=old,native_recomputed=False,reason='CURRENT_PREVIEW_UX_RED_PATH'))
    target=root/updated['preview_id']/'preview.json'
    target.parent.mkdir(parents=True,exist_ok=False)
    LocalStorage._write_json(target,json.dumps(updated,indent=2,allow_nan=False))
    claim=dict(path=str(target),sha256=sha(target))
    verify_preview(claim,project=project)
    LocalStorage._write_json(cached,json.dumps(claim))
    return claim


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-id',type=UUID,required=True)
    parser.add_argument('--backend',choices=('dataset_stp','dataset_v2'),default='dataset_stp')
    parser.add_argument('--kind',choices=('path','robot','both'),default='both')
    args=parser.parse_args()
    try:
        for kind in ('path','robot') if args.kind=='both' else (args.kind,):
            claim=refresh(args.artifact_id,backend=args.backend,kind=kind)
            d=read(claim['path'])
            print(json.dumps(dict(status='PREVIEW_UX_REBOUND',kind=kind,preview_id=d['preview_id'],
                package_id=d['package_id'],artifact_id=d['artifact_id'],source_point_count=d['source_point_count'],
                playback_point_count=d['playback_point_count'],native_recomputed=False,isaac_launched=False)))
    except (OSError,ValueError,KeyError,TypeError):
        raise SystemExit('PREVIEW_UX_REBIND_REJECTED: source evidence or audited release differs')

