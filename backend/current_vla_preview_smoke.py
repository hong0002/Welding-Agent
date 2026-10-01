"""Explicit one-shot current-job API -> Isaac preview smoke. Never invokes models."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import time
from uuid import UUID, uuid4

import numpy as np
from dotenv import load_dotenv
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.orchestrator.workflow import Workflow
from backend.services.current_preview_gate import sha, read
from backend.services.current_vla_preview import PROJECT
from backend.services.storage import LocalStorage

JOB = '3fe35636-df6d-46b0-9089-9260ac99ad3e'
STORAGE = PROJECT / '.cache/module-integration-e2e/f525de57-eabd-47b4-bd3c-8686805d748b/storage'
ORIGINAL = PROJECT / '.cache/native-models/guided-vla/866654a5-8cc7-4edc-82a8-0c276818aad8/trajectory.npz'
REFERENCE_PACKAGE = PROJECT / '.cache/simulator/prediction-packages/44c5b519-f021-4427-89b9-700c1f277c31/package.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    args = parser.parse_args()
    load_dotenv(PROJECT / '.env', override=True)
    report_dir = PROJECT / '.cache/current-vla-preview-smoke' / str(uuid4())
    report_dir.mkdir(parents=True, exist_ok=False)

    def event(stage, **details):
        entry = dict(at=datetime.now(timezone.utc).isoformat(), stage=stage, **details)
        with (report_dir/'stages.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(entry, allow_nan=False)+'\n')
        print(json.dumps(entry, ensure_ascii=False), flush=True)

    workflow = Workflow(LocalStorage(STORAGE))
    job = workflow.storage.get_job(UUID(JOB))
    proof = read(workflow.storage.artifact_path('native_context',job.vla_prediction.artifact_id,'.vla.json'))
    source = Path(proof['directory']) / 'trajectory.npz'
    reference = read(REFERENCE_PACKAGE)
    reference_npz = Path(reference['prediction_root'])/reference['sample_id']/'trajectory.npz'
    assert reference['artifact_id'] == str(job.vla_prediction.artifact_id)
    assert sha(source) == sha(ORIGINAL) == sha(reference_npz) == reference['provenance']['source_files']['trajectory.npz']
    retained = [source, ORIGINAL, REFERENCE_PACKAGE, reference_npz,
                workflow.storage.artifact_path('jobs',job.id,'.json')]
    from backend.services.simulator_prediction_package import PackageSettings
    sim = PackageSettings.from_env().simulator_root
    for name, digest in reference['provenance']['simulator_files'].items():
        assert sha(sim/name) == digest
        retained.append(sim/name)
    retained.append(sim/'prepare_rb5_h5_trajectory.py')
    before = {str(p):sha(p) for p in retained}
    with np.load(source, allow_pickle=False) as current, np.load(ORIGINAL, allow_pickle=False) as original:
        for key in ('predicted_path_m','ground_truth_path_m'):
            np.testing.assert_array_equal(current[key],original[key])
        assert current['predicted_path_m'].shape==(9,3)
    event('preflight_current_job', job_id=JOB, artifact_id=str(job.vla_prediction.artifact_id),
          reference_package_id=reference['package_id'], point_count=9, npz_sha256=sha(source))
    with TestClient(create_app(workflow=workflow)) as api:
        runtime = api.app.state.preview_runtime
        record = dict(job_id=JOB,artifact_id=str(job.vla_prediction.artifact_id),sample_id=job.scene.sample_id,
            original_live_artifact_id='f2bba528-fb2b-46a6-8c57-d0e1ba10211c',same_prediction_as_live=True,
            reference_package_id=reference['package_id'], same_npz_as_reference_package=True,
            inference_calls=0,isaac_launches=0,api_calls=0,existing_sample_replay_used=False,
            model_calls={name:0 for name in ('Segment','Rough','trajectory2','Guided_VLA','OpenAI','SSH_retrieval')})
        try:
            # Exclusive audit record precedes exactly one POST. No retry path.
            with (report_dir/'submission.json').open('x',encoding='utf-8') as stream:
                json.dump(dict(route='/api/simulator/preview-current-vla',job_id=JOB,post_count=1),stream)
            record['api_calls'] = 1
            event('api_request_sent', route='/api/simulator/preview-current-vla')
            response = api.post('/api/simulator/preview-current-vla',json={'job_id':JOB})
            if response.status_code != 202:
                record.update(verdict='CURRENT_PREVIEW_ADMISSION_FAILED',http_status=response.status_code)
                return
            record['isaac_launches'] = 1
            event('api_request_admitted', http_status=202, package_id=runtime.latest['package_id'])
            event('isaac_process_launched', pid=runtime.process.pid)
            print(json.dumps(dict(stage='launched_once',session=str(runtime.session),report=str(report_dir)),ensure_ascii=False),flush=True)
            deadline = time.monotonic()+runtime.config.startup_timeout+runtime.config.sample_timeout+30
            while time.monotonic() < deadline:
                status = api.get('/api/simulator/status').json()['current_preview']
                if status['latest'] and status['latest']['status'] in {'SUCCEEDED','FAILED'}:
                    break
                time.sleep(.5)
            record['status'] = status
            record['session'] = str(runtime.session)
            record['native_log'] = str(runtime.session/'native.log')
            if status['latest'] and status['latest']['status']=='SUCCEEDED':
                output = runtime.session/'outputs'/status['latest']['request_id']
                report = read(output/'report.json')
                with np.load(output/'waypoints.npz',allow_pickle=False) as shown, np.load(source,allow_pickle=False) as current:
                    np.testing.assert_array_equal(shown['predicted_path_m'],current['predicted_path_m'])
                record.update(verdict='CURRENT_WEB_VLA_SIMULATOR_PREVIEW_PASS',isaac_report=report,output=str(output))
            else:
                record['verdict']='CURRENT_WEB_VLA_SIMULATOR_PREVIEW_INCOMPLETE'
                failure = runtime.session/'results'/((status.get('latest') or {})['request_id']+'.json')
                if failure.is_file():
                    record['failure'] = read(failure)
                    phase = record['failure'].get('phase','unknown')
                    record['verdict'] = ('CURRENT_VLA_PREVIEW_DAE_FAIL' if phase=='robot_visuals' else
                        'CURRENT_VLA_PREVIEW_IK_FAIL' if phase=='native_ik' else
                        'CURRENT_VLA_PREVIEW_SCENE_FAIL' if phase=='stage_geometry' else
                        'CURRENT_VLA_PREVIEW_PLAYBACK_FAIL' if phase.startswith('waypoint_') else
                        'CURRENT_VLA_PREVIEW_CAPTURE_FAIL' if phase.startswith('capture_') else
                        'CURRENT_WEB_VLA_SIMULATOR_PREVIEW_INCOMPLETE')
            record['source_hashes_preserved'] = all(sha(p)==digest for p,digest in before.items())
            assert record['source_hashes_preserved']
        finally:
            record['cleanup_requested'] = True
            owned = runtime.process
            event('process_cleanup_started')
            api.post('/api/simulator/stop',json={})
            record['cleanup_complete'] = runtime.process is None and runtime.lease is None
            record['process_exit_code_after_owned_cleanup'] = owned.poll() if owned else None
            event('process_cleanup_completed', complete=record['cleanup_complete'])
            (report_dir/'report.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(dict(verdict=record.get('verdict','INCOMPLETE'),report=str(report_dir/'report.json')),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
