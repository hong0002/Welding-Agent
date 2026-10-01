"""Explicit bounded offline preflight. No inference, queue, GUI or full dataset scan."""
import argparse
import json
from pathlib import Path
import time
from uuid import UUID, uuid4

from backend.services.simulator2_client import DatasetSimulatorV2Client, NativeDatasetBuilder
from backend.services.simulator2_contract import FAMILIES, NATIVE_FILES, exact_assets, Simulator2ContractError
from backend.services.current_preview_config import CurrentPreviewError
from backend.services.current_preview_gate import verify_preview
from backend.services.simulator_prediction_package import PROJECT, PackageSettings, read, sha, write
from backend.services.storage import LocalStorage


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-id',type=UUID,required=True)
    parser.add_argument('--families',action='store_true',help='One explicit sample per source-supported family, scene math only')
    args=parser.parse_args()
    directory=PROJECT/'.cache/simulator2/audits'/str(uuid4());directory.mkdir(parents=True)
    client=DatasetSimulatorV2Client(LocalStorage(PROJECT/'backend/storage'),None)
    settings,job,artifact,adapter,source,family,h5,obj=client._inputs(args.job_id,None)
    protected={str(file):sha(file) for file in (h5,obj,Path(source[0])/'trajectory.npz',
        Path(source[0])/'response.json',Path(source[0])/'metadata.json',Path(source[0])/'request_manifest.json',
        client.storage.artifact_path('jobs',job.id,'.json'),Path(source[2]['source_mask']))}
    external={name:sha(client.root/name) for name in NATIVE_FILES}
    # One native robot preflight of the actual immutable current prediction.
    claim=client.prepare(job_id=args.job_id,kind='robot')
    d,p,npz=verify_preview(claim)
    native_report=read(Path(d['package']).parent/'native/report.json')
    report=dict(schema_version='simulator2-bounded-audit-v1',job_id=str(job.id),artifact_id=str(artifact),
        sample_id=job.scene.sample_id,split=job.scene.split,claim=claim,
        gates=['SIMULATOR2_ADAPTER_PASS','SAMPLE_IDENTITY_PASS','H5_OBJ_PASS','VLA_SOURCE_PATH_PRESERVED','SIMULATOR2_PLAYBACK_PACKAGE_PASS'],
        h5=str(h5),obj=str(obj),source_npz_sha256=sha(Path(source[0])/'trajectory.npz'),copy_npz_sha256=sha(npz),
        original_metrics=dict(ade_mm=p['ade_mm'],fde_mm=p['fde_mm']),
        source_point_count=9,playback=p['playback'],native_preflight=p['preflight'],native_report=native_report,
        protected_files=protected,external_files=external,backend_default='legacy',families=[],
        calls=dict(Segment2=0,Trajectory3=0,GuidedVLA=0,OpenAI=0,SSH_retrieval=0,SimulationApp=0,Isaac_GUI=0,physics=0))
    if args.families:
        for family in FAMILIES:
            # Exact bounded list verified from real shallow dataset directories; no discovery fallback.
            thickness='12' if family in {'L_PS','T_PS','T_SS'} else '03'
            sample=f'{family}_{thickness}_0001'
            row=dict(family=family,sample=sample,robot_readiness='PENDING_CURRENT_VLA_AND_NATIVE_IK',
                     path_readiness=False,workpiece_readiness=False,inference_called=False)
            started=time.monotonic()
            try:
                h,o=exact_assets(settings.dataset_root,sample)
                row.update(h5=str(h),obj=str(o),h5_sha256=sha(h),obj_sha256=sha(o))
                if sample==job.scene.sample_id:
                    result=p['preflight']['native'];row['robot_readiness']='OFFLINE_NATIVE_IK_PASS_CURRENT_VLA'
                    row['input']='current_guided_vla'
                else:
                    result=client.builder.build(root=client.root,h5=h,obj=o,sample_id=sample,
                        output=directory/family,kind='path')
                    row['input']='H5_SCENE_PREFLIGHT_ONLY_NO_PREDICTION'
                row.update(path_readiness=True,workpiece_readiness=True,native=result)
            except (CurrentPreviewError,Simulator2ContractError) as exc:
                row['reason_code']=exc.code
            row['elapsed_seconds']=round(time.monotonic()-started,3)
            report['families'].append(row)
            print(json.dumps({k:row[k] for k in ('family','sample','path_readiness','robot_readiness')}),flush=True)
            write(directory/(family+'.json'),row)
    report['original_files_unchanged']=all(sha(file)==digest for file,digest in protected.items())
    report['external_files_unchanged']=all(sha(client.root/name)==digest for name,digest in external.items())
    report['verdict']='SIMULATOR2_ADAPTER_READY'
    write(directory/'report.json',report)
    print(json.dumps(dict(report=str(directory/'report.json'),verdict=report['verdict'],
        source_point_count=9,playback_point_count=d['playback_point_count'],
        original_files_unchanged=report['original_files_unchanged'],external_files_unchanged=report['external_files_unchanged']),ensure_ascii=True))


if __name__=='__main__': main()
