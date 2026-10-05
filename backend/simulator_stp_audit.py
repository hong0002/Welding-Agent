import sys as _release_sys
from pathlib import Path as _ReleasePath
_release_sys.path.insert(0, str(_ReleasePath(__file__).resolve().parents[1]))
from backend.services.project_paths import native_parent
"""Explicit bounded native math only. No inference, queue, GUI or dataset scan."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import time
from uuid import UUID, uuid4

from backend.services.current_preview_config import CurrentPreviewError
from backend.services.current_preview_gate import verify_preview
from backend.services.simulator2_contract import FAMILIES, exact_assets, Simulator2ContractError
from backend.services.simulator_stp_client import DatasetSimulatorStpClient, inspect_native_contract
from backend.services.simulator_prediction_package import PROJECT, sha, read, write
from backend.services.storage import LocalStorage

ARTIFACT=UUID('6c4cb794-5190-48ad-ad75-c38660b26e5c')
SAMPLE='B_PP_03_0006'


def audit(*, families=False):
    root=native_parent(PROJECT)/'simulator_stp'
    evidence=inspect_native_contract(root)
    directory=PROJECT/'.cache/simulator-stp/audits'/str(uuid4())
    directory.mkdir(parents=True,exist_ok=False)
    storage=LocalStorage(PROJECT/'backend/storage')
    proof_path=storage.artifact_path('native_context',ARTIFACT,'.vla.json')
    proof=read(proof_path)
    job_id=UUID(proof['job_id'])
    client=DatasetSimulatorStpClient(storage,None,root=root)
    settings,job,artifact,adapter,source,family,h5,obj=client._inputs(job_id,ARTIFACT)
    attempt,trajectory,manifest,hashes,_=source
    if trajectory.sample_id!=SAMPLE or job.scene.sample_id!=SAMPLE or artifact!=ARTIFACT:
        raise ValueError('Requested current artifact identity differs')
    protected={str(file):sha(file) for file in (PROJECT/'.env',proof_path,h5,obj,
        storage.artifact_path('jobs',job.id,'.json'),Path(manifest['source_mask']),
        attempt/'request_manifest.json',attempt/'completion.json',*(attempt/name for name in hashes))}
    protected.update({str(client.root/name):digest for name,digest in evidence['native_files'].items()})
    for file in (root/'데이터수집 환경구축.stp',client.root/'[STEP]ATU01035.stp'):
        if file.is_file(): protected[str(file)]=sha(file)
    # Preserve prior reports/readiness: no migration or rewrite of existing packages.
    for file in (PROJECT/'.cache/simulator-stp/audits/c4516838-ad22-414d-bce9-bd5b9ca40073/audit.json',
                 PROJECT/'.cache/simulator2/readiness'/str(ARTIFACT)/'robot.json'):
        if file.is_file():
            protected[str(file)]=sha(file)
            if file.name=='robot.json':
                descriptor=Path(read(file)['path']);protected[str(descriptor)]=sha(descriptor)
                package=Path(read(descriptor)['package']);protected[str(package)]=sha(package)
                for name in ('trajectory_solution.npz','report.json'):
                    native=package.parent/'native'/name;protected[str(native)]=sha(native)
    report=dict(schema_version='simulator-stp-layout-audit-v1',audited_at=datetime.now(timezone.utc).isoformat(),
        job_id=str(job_id),artifact_id=str(artifact),sample_id=SAMPLE,split=trajectory.split,family=family,
        h5=str(h5),obj=str(obj),source_npz_sha256=hashes['trajectory.npz'],source_point_count=9,
        original_metrics={'ade_mm':trajectory.ade_mm,'fde_mm':trajectory.fde_mm},native_contract=evidence,
        layout='stp',cad_source='sample_obj',environment_source='stp_reference_layout',
        simulation_only=True,fixture_ready=False,validated_simulation=False,physical_robot_executable=False,
        orientation_source='simulator_stp_policy',vla_orientation=False,path_pass=False,robot_pass=False,
        live_smoke='SIMULATOR_STP_LAYOUT_LIVE_SMOKE_PENDING',protected_files=protected,families=[],
        calls={name:0 for name in ('Segment2','YOLO','Trajectory3','GuidedVLA','OpenAI','SSH','Isaac','GUI','physics')})
    for kind in ('path','robot'):
        started=time.monotonic()
        try:
            # Path is admitted first. Robot uses native full IK/FK once, never a renderer solver.
            if kind=='robot' and not report['path_pass']: break
            claim=client.prepare(job_id=job_id,artifact_id=ARTIFACT,kind=kind)
            d,p,npz=verify_preview(claim)
            native_report=read(Path(d['package']).parent/'native/report.json')
            report[kind+'_pass']=True
            report[kind]=dict(claim=claim,package=d['package'],source_copy_sha256=sha(npz),
                source_to_scene=d['source_to_scene'],playback=p['playback'],native=p['preflight']['native'],
                native_report=native_report,visuals=d['visual_geometry_preflight'])
        except CurrentPreviewError as exc:
            report[kind]={'reason_code':exc.code}
        report[kind]['elapsed_seconds']=round(time.monotonic()-started,3)
        print(kind.upper()+' '+('PASS' if report[kind+'_pass'] else report[kind]['reason_code']),flush=True)
        write(directory/(kind+'.json'),report[kind])
    if families:
        for family in FAMILIES:
            thickness='12' if family in {'L_PS','T_PS','T_SS'} else '03'
            sample=f'{family}_{thickness}_0001'
            row=dict(family=family,sample=sample,obj_workpiece_support=False,stp_layout_scene_support=False,
                robot_readiness='NOT_TESTED',input='H5_SCENE_PREFLIGHT_ONLY_NO_VLA_PREDICTION',inference_called=False)
            started=time.monotonic()
            try:
                h,o=exact_assets(settings.dataset_root,sample)
                row.update(h5=str(h),obj=str(o),h5_sha256=sha(h),obj_sha256=sha(o),obj_workpiece_support=True)
                result=client.builder.build(root=client.root,h5=h,obj=o,sample_id=sample,output=directory/family,kind='path')
                row.update(stp_layout_scene_support=True,native=result)
                row['assets_unchanged']=sha(h)==row['h5_sha256'] and sha(o)==row['obj_sha256']
            except (CurrentPreviewError,Simulator2ContractError) as exc:
                row['reason_code']=exc.code
            row['elapsed_seconds']=round(time.monotonic()-started,3)
            report['families'].append(row)
            write(directory/(family+'.json'),row)
            print(f"FAMILY {family}: OBJ={row['obj_workpiece_support']} STP_SCENE={row['stp_layout_scene_support']}",flush=True)
    report['protected_files_unchanged']=all(sha(file)==digest for file,digest in protected.items())
    report['verdict']=('SIMULATOR_STP_LAYOUT_ROBOT_PREFLIGHT_READY' if report['robot_pass'] else
        'SIMULATOR_STP_LAYOUT_PATH_READY' if report['path_pass'] else 'SIMULATOR_STP_LAYOUT_ADAPTER_READY')
    write(directory/'report.json',report)
    print(str(directory/'report.json'),flush=True)
    return directory/'report.json'


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--families',action='store_true')
    audit(families=parser.parse_args().families)
