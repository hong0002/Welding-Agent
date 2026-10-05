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


# Exact pre-selection-proof renderer release; native/source files remain immutable.
PRE_SELECTION_OWNED_CODE = {'dataset_v2': {'backend/current_vla_isaac_preview.py': 'e0399dcba9ac9c01a95989b7a2cc87b4137b33e7cd353d79bfd481a87a7aa9a0',
                'backend/services/current_preview_gate.py': 'ad4b4c36177fef4da67ff7bcfbba061ac2eb0e1ef774804dba26a36d061602ff',
                'backend/services/simulator2_gate.py': '60ec44755be345e57eac11f18c69daaf400fdcf59e86006de28f09f8d26b4c6f',
                'backend/services/simulator2_client.py': 'e622a3069b180bf09bca36ead6c678fcee42e75df2a5fda103dd2c8c4e322289',
                'backend/services/simulator2_contract.py': 'b68c0f7139f7c04103cf453d218a4323fe5f59761e74fd7e0f4a15c19f853f40',
                'backend/simulator2_prepare.py': '93dcbcb040f0107c8422c2348224750626245cf523e173c0f881594da47fb1fe',
                'backend/services/preview_capture.py': 'e254ea46267233c01b68565486845b3d10cd7a7741ee43ec609bf79ad765919e',
                'backend/services/preview_visual_style.py': 'a826f53f38be7cbe32f4db972c58ac748ddb1d92d1a178aa2e4d10cc8d285230',
                'backend/services/preview_live_producer.py': 'e7bd9700451f734750946953324df1e2f5f09c2993a948ed1c68e21f6c60258f',
                'backend/services/final_prediction_proof.py': 'b1883fe4d1e2564a2fac62483b0af72e3365f1616ce62d66bed319d92ae66303'},
 'dataset_stp': {'backend/current_vla_isaac_preview.py': 'e0399dcba9ac9c01a95989b7a2cc87b4137b33e7cd353d79bfd481a87a7aa9a0',
                 'backend/services/current_preview_gate.py': 'ad4b4c36177fef4da67ff7bcfbba061ac2eb0e1ef774804dba26a36d061602ff',
                 'backend/services/simulator2_gate.py': '60ec44755be345e57eac11f18c69daaf400fdcf59e86006de28f09f8d26b4c6f',
                 'backend/services/simulator2_client.py': 'e622a3069b180bf09bca36ead6c678fcee42e75df2a5fda103dd2c8c4e322289',
                 'backend/services/simulator2_contract.py': 'b68c0f7139f7c04103cf453d218a4323fe5f59761e74fd7e0f4a15c19f853f40',
                 'backend/simulator2_prepare.py': '93dcbcb040f0107c8422c2348224750626245cf523e173c0f881594da47fb1fe',
                 'backend/services/preview_capture.py': 'e254ea46267233c01b68565486845b3d10cd7a7741ee43ec609bf79ad765919e',
                 'backend/services/preview_visual_style.py': 'a826f53f38be7cbe32f4db972c58ac748ddb1d92d1a178aa2e4d10cc8d285230',
                 'backend/services/preview_live_producer.py': 'e7bd9700451f734750946953324df1e2f5f09c2993a948ed1c68e21f6c60258f',
                 'backend/services/final_prediction_proof.py': 'b1883fe4d1e2564a2fac62483b0af72e3365f1616ce62d66bed319d92ae66303',
                 'backend/services/simulator_stp_gate.py': '01c60faa7d943f297f3eaefca4dee59d1e744be5fc1535975803faf4bf1756a1',
                 'backend/services/simulator_stp_contract.py': '348c72b49e24ea20f8cf47991b4f8a1fe551b0829bfccd9c2a3e799c1fe67d42',
                 'backend/services/simulator_stp_client.py': '9eb9c3e4464972b1142070d91e1c762fc24beb8723d20f8c0c61255d848c609f',
                 'backend/simulator_stp_prepare.py': 'e73ba4a12028c545d930c04acc072b70f15e9f75e6913456af30522e90fd7394',
                 'backend/services/preview_environment.py': '9860ea7fd1b7c5396494d1335f87e56750d3fdde8c3225f46321e3e059b7b411'}}

# Exact previous source-binding release; preserve native solutions and source packages.
PRE_FULL_SCENE_OWNED_CODE = {'dataset_stp': {'backend/current_vla_isaac_preview.py': '82f8ecd83b0e135c178f44c47cb439ad1bb4e0d7af7227c85c6827e70dda3636',
                 'backend/services/current_preview_gate.py': 'ad4b4c36177fef4da67ff7bcfbba061ac2eb0e1ef774804dba26a36d061602ff',
                 'backend/services/simulator2_gate.py': 'ac359ad616cc0795d280d5abf3d9450206a4d5dae4a5547d736fd0b8a45e4c60',
                 'backend/services/simulator2_client.py': 'b9c306fd7d7d6264782481bf6618a00d922b1e458a211508b3df4bb3e652f1f3',
                 'backend/services/simulator2_contract.py': 'b68c0f7139f7c04103cf453d218a4323fe5f59761e74fd7e0f4a15c19f853f40',
                 'backend/simulator2_prepare.py': '93dcbcb040f0107c8422c2348224750626245cf523e173c0f881594da47fb1fe',
                 'backend/services/preview_capture.py': 'e254ea46267233c01b68565486845b3d10cd7a7741ee43ec609bf79ad765919e',
                 'backend/services/preview_visual_style.py': 'a826f53f38be7cbe32f4db972c58ac748ddb1d92d1a178aa2e4d10cc8d285230',
                 'backend/services/preview_live_producer.py': 'e7bd9700451f734750946953324df1e2f5f09c2993a948ed1c68e21f6c60258f',
                 'backend/services/final_prediction_proof.py': 'b1883fe4d1e2564a2fac62483b0af72e3365f1616ce62d66bed319d92ae66303',
                 'backend/services/prediction_path_evidence.py': '8fef0bb394fda34967b249e53f7b260cf9a3c088aa49fb27b1b93e70b6596cf1',
                 'backend/services/simulator_stp_gate.py': '01c60faa7d943f297f3eaefca4dee59d1e744be5fc1535975803faf4bf1756a1',
                 'backend/services/simulator_stp_contract.py': '348c72b49e24ea20f8cf47991b4f8a1fe551b0829bfccd9c2a3e799c1fe67d42',
                 'backend/services/simulator_stp_client.py': '9eb9c3e4464972b1142070d91e1c762fc24beb8723d20f8c0c61255d848c609f',
                 'backend/simulator_stp_prepare.py': 'e73ba4a12028c545d930c04acc072b70f15e9f75e6913456af30522e90fd7394',
                 'backend/services/preview_environment.py': '9860ea7fd1b7c5396494d1335f87e56750d3fdde8c3225f46321e3e059b7b411'},
 'dataset_v2': {'backend/current_vla_isaac_preview.py': '82f8ecd83b0e135c178f44c47cb439ad1bb4e0d7af7227c85c6827e70dda3636',
                'backend/services/current_preview_gate.py': 'ad4b4c36177fef4da67ff7bcfbba061ac2eb0e1ef774804dba26a36d061602ff',
                'backend/services/simulator2_gate.py': 'ac359ad616cc0795d280d5abf3d9450206a4d5dae4a5547d736fd0b8a45e4c60',
                'backend/services/simulator2_client.py': 'b9c306fd7d7d6264782481bf6618a00d922b1e458a211508b3df4bb3e652f1f3',
                'backend/services/simulator2_contract.py': 'b68c0f7139f7c04103cf453d218a4323fe5f59761e74fd7e0f4a15c19f853f40',
                'backend/simulator2_prepare.py': '93dcbcb040f0107c8422c2348224750626245cf523e173c0f881594da47fb1fe',
                'backend/services/preview_capture.py': 'e254ea46267233c01b68565486845b3d10cd7a7741ee43ec609bf79ad765919e',
                'backend/services/preview_visual_style.py': 'a826f53f38be7cbe32f4db972c58ac748ddb1d92d1a178aa2e4d10cc8d285230',
                'backend/services/preview_live_producer.py': 'e7bd9700451f734750946953324df1e2f5f09c2993a948ed1c68e21f6c60258f',
                'backend/services/final_prediction_proof.py': 'b1883fe4d1e2564a2fac62483b0af72e3365f1616ce62d66bed319d92ae66303',
                'backend/services/prediction_path_evidence.py': '8fef0bb394fda34967b249e53f7b260cf9a3c088aa49fb27b1b93e70b6596cf1'}}

FINAL_PROOF_CODE = 'backend/services/final_prediction_proof.py'

# Exact companion release which accidentally imported backend dotenv settings
# into the pre-GUI gate. Only this import dependency changes; proofs stay strict.
FINAL_COMPANION_CODE = 'backend/services/gpt2_simulator_companion.py'
PRE_FINAL_COMPANION_SHA = 'aa24a89987c3f7a8a41d016c8eb1ddfb0d9896733deea12291b005b8e4aeedb4'


def refresh_final(artifact_id, *, kind='robot', project=None, job_id=None, check_only=False):
    """Reissue only a descriptor for the exact audited import-only fix."""
    from backend.services.simulator_final_gate import OWNED_CODE, verify
    artifact_id = str(UUID(str(artifact_id)))
    project = (project or Path(__file__).resolve().parents[1]).resolve()
    if kind != 'robot': raise ValueError('Final native renderer requires robot preview')
    cached = project/'.cache/simulator-final/readiness'/artifact_id/(kind+'.json')
    old = read(cached); path = Path(old['path']).resolve()
    root = project/'.cache/simulator/current-previews/packages'
    if (path.parent.parent!=root or path.name!='preview.json' or
            str(UUID(path.parent.name))!=path.parent.name or sha(path)!=old['sha256']):
        raise ValueError('Invalid immutable descriptor')
    d=read(path)
    if (d['backend']!='dataset_final' or d['artifact_id']!=artifact_id or
            d['kind']!=kind or d['preview_id']!=path.parent.name or
            (job_id is not None and d['job_id']!=str(UUID(str(job_id))))):
        raise ValueError('Wrong current preview identity')
    code_root=Path(__file__).resolve().parents[1]
    current={name:sha(code_root/name) for name in OWNED_CODE}
    if d['owned_code']==current:
        verify_preview(old,project=project)
        return old
    previous={**current,FINAL_COMPANION_CODE:PRE_FINAL_COMPANION_SHA}
    if d['owned_code']!=previous:
        raise ValueError('Unknown stale renderer release')
    updated=copy.deepcopy(d);updated['owned_code']=current
    # Recheck every native/package/source/approval/current-job binding unchanged.
    verify(updated,path,project)
    if check_only:return old
    updated.update(preview_id=str(uuid4()),ux_renderer_refresh=dict(
        previous_descriptor=old,native_recomputed=False,
        reason='GPT2_COMPANION_BACKEND_IMPORT_REMOVED',added_fingerprints=[]))
    target=root/updated['preview_id']/'preview.json'
    target.parent.mkdir(parents=True,exist_ok=False)
    LocalStorage._write_json(target,json.dumps(updated,indent=2,allow_nan=False))
    claim=dict(path=str(target),sha256=sha(target))
    verify_preview(claim,project=project)
    LocalStorage._write_json(cached,json.dumps(claim))
    return claim

# Exact pre-restoration code and the recorded successful STP Robot release.
# Rebind descriptors only; their original native solution/XYZ stay unchanged.
PRE_STRICT_OWNED_CODE = {
    backend:{**values,
        'backend/current_vla_isaac_preview.py':'e0399dcba9ac9c01a95989b7a2cc87b4137b33e7cd353d79bfd481a87a7aa9a0',
        'backend/services/current_preview_gate.py':'ad4b4c36177fef4da67ff7bcfbba061ac2eb0e1ef774804dba26a36d061602ff',
        'backend/services/simulator2_gate.py':'1b1d0c1581f11e0fcc6344afccd76f59de92b6b9ca6da372c05d9695ffd5b088',
        'backend/services/simulator2_client.py':'6893b0160a50e92e13ba53fa9d202a16892299b62297a6b09b6c29674092f8c0',
        'backend/services/preview_visual_style.py':'a826f53f38be7cbe32f4db972c58ac748ddb1d92d1a178aa2e4d10cc8d285230',
        'backend/services/preview_live_producer.py':'e7bd9700451f734750946953324df1e2f5f09c2993a948ed1c68e21f6c60258f',
        FINAL_PROOF_CODE:'b3c968463d1ab9eaec0eeb98e27fd9f4bdacbd5e4e2c25e56b3121f24a132fbb'}
    for backend,values in PRE_LIVE_OWNED_CODE.items()
}
SUCCESSFUL_ROBOT_OWNED_CODE = {
    backend:{**values,
        'backend/services/current_preview_gate.py':'3d3e5b473152ad5961b1c82b07a8192b233efc23de648bcc1c619cc5362099f0',
        FINAL_PROOF_CODE:'dffc94eab1c3b508bc192a8517f2c47446710ba34b0196522fc94e5cdf5b333c'}
    for backend,values in PRE_STRICT_OWNED_CODE.items()
}


def refresh(artifact_id, *, backend='dataset_stp', kind='robot', project=None,
            job_id=None, check_only=False):
    if backend=='dataset_final':
        return refresh_final(artifact_id,kind=kind,project=project,job_id=job_id,check_only=check_only)
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
    restore_release=d['owned_code'] in (PRE_STRICT_OWNED_CODE[backend],SUCCESSFUL_ROBOT_OWNED_CODE[backend],PRE_SELECTION_OWNED_CODE[backend],PRE_FULL_SCENE_OWNED_CODE[backend])
    if not proof_addition and not restore_release and d['owned_code'] not in (PRE_UX_OWNED_CODE[backend], PRE_LIVE_OWNED_CODE[backend]):
        raise ValueError('Unknown stale renderer release')
    updated=copy.deepcopy(d);updated['owned_code']=current
    # Unchanged normal gate verifies ALL native/source/approval/asset evidence.
    # Only the exact allowlisted owned-code release is replaced in memory.
    verify(updated,path,project)
    if check_only:
        return old
    updated.update(preview_id=str(uuid4()),ux_renderer_refresh=dict(
        previous_descriptor=old,native_recomputed=False,
        reason='FINAL_PREDICTION_PROOF_FINGERPRINT_ADDED' if proof_addition else 'STRICT_ROBOT_PATH_RESTORED' if restore_release else 'CURRENT_PREVIEW_LIVE_RED_PATH',
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
    if getattr(client, 'backend', None) not in (*PRE_UX_OWNED_CODE,'dataset_final'):
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
    parser.add_argument('--backend',choices=('dataset_stp','dataset_v2','dataset_final'),default='dataset_stp')
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
