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

# Exact renderer release audited before the live-view upgrade. This is an
# explicit descriptor-only migration, never a wildcard fingerprint bypass.
PRE_LIVE_OWNED_CODE = {
    backend: {**values,
        'backend/current_vla_isaac_preview.py': '0b8b03984c27314ffbdabb810078b4f18c5be49766ca3dfe0f6eb975af3a955f',
        'backend/services/simulator2_gate.py': 'de186d532d4fbb58919d4e8ed689eb02991fddfee6a7e2f76bafaac02d492410',
        'backend/services/preview_visual_style.py': '13506ec4050e9c6966287d8a985f962ffd8dc8461aa63d7d0c098699fe5d28d2'}
    for backend, values in PRE_UX_OWNED_CODE.items()
}


FINAL_PROOF_CODE = 'backend/services/final_prediction_proof.py'


def refresh(artifact_id, *, backend='dataset_stp', kind='robot', project=None,
            job_id=None, check_only=False):
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
    if job_id is not None and d['job_id'] != str(UUID(str(job_id))):
        raise ValueError('Wrong current job identity')
    if backend=='dataset_stp':
        from backend.services.simulator_stp_gate import OWNED_CODE, verify
    else:
        from backend.services.simulator2_gate import OWNED_CODE, verify
    code_root=Path(__file__).resolve().parents[1]
    current={name:sha(code_root/name) for name in OWNED_CODE}
    if d['owned_code']==current:
        verify_preview(old,project=project)
        return old
    # One known contract addition only. Every previously present code hash must
    # still equal the current file; extra/missing/changed entries are rejected.
    previous_final_proof = {name: digest for name, digest in current.items() if name != FINAL_PROOF_CODE}
    proof_addition = FINAL_PROOF_CODE in current and d['owned_code'] == previous_final_proof
    if not proof_addition and d['owned_code'] not in (PRE_UX_OWNED_CODE[backend], PRE_LIVE_OWNED_CODE[backend]):
        raise ValueError('Unknown stale renderer release')
    updated=copy.deepcopy(d);updated['owned_code']=current
    # Unchanged normal gate verifies ALL native/source/approval/asset evidence.
    # Only the exact allowlisted owned-code release is replaced in memory.
    verify(updated,path,project)
    if check_only:
        return old
    updated.update(preview_id=str(uuid4()),ux_renderer_refresh=dict(
        previous_descriptor=old,native_recomputed=False,
        reason='FINAL_PREDICTION_PROOF_FINGERPRINT_ADDED' if proof_addition else 'CURRENT_PREVIEW_LIVE_RED_PATH',
        added_fingerprints=[FINAL_PROOF_CODE] if proof_addition else []))
    target=root/updated['preview_id']/'preview.json'
    target.parent.mkdir(parents=True,exist_ok=False)
    LocalStorage._write_json(target,json.dumps(updated,indent=2,allow_nan=False))
    claim=dict(path=str(target),sha256=sha(target))
    verify_preview(claim,project=project)
    LocalStorage._write_json(cached,json.dumps(claim))
    return claim


def refresh_current(client, job_id):
    """Explicit current-job action reusing the audited metadata-only migration."""
    from backend.services.current_preview_config import CurrentPreviewError
    if getattr(client, 'backend', None) not in PRE_UX_OWNED_CODE:
        raise CurrentPreviewError('PREVIEW_DESCRIPTOR_REFRESH_REJECTED', 'Descriptor refresh requires a dataset preview backend.', 409)
    if client.runtime.status().get('can_stop'):
        raise CurrentPreviewError('PREVIEW_DESCRIPTOR_REFRESH_REJECTED', 'Stop the current preview before refreshing its descriptor.', 409)
    try:
        settings, job, artifact, *_ = client._inputs(job_id, None)
        directory = settings.project/'.cache'/client.cache_namespace/'readiness'/str(artifact)
        kinds = [kind for kind in ('path','robot') if (directory/(kind+'.json')).is_file()]
        if not kinds:
            raise ValueError('No existing descriptor to refresh')
        # Validate every cached kind before writing any new descriptor.
        for kind in kinds:
            refresh(artifact, backend=client.backend, kind=kind, project=settings.project,
                    job_id=job.id, check_only=True)
        result = []
        for kind in kinds:
            old = read(directory/(kind+'.json'))
            claim = refresh(artifact, backend=client.backend, kind=kind, project=settings.project, job_id=job.id)
            d = read(claim['path'])
            result.append(dict(kind=kind, preview_id=d['preview_id'], changed=claim != old))
        return dict(status='PREVIEW_DESCRIPTOR_REFRESHED', artifact_id=str(artifact), previews=result,
                    native_recomputed=False, isaac_launched=False)
    except CurrentPreviewError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise CurrentPreviewError('PREVIEW_DESCRIPTOR_REFRESH_REJECTED',
            'Descriptor refresh rejected: current identity, source evidence or known code release differs.', 409) from None


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
