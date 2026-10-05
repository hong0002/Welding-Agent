import sys as _release_sys
from pathlib import Path as _ReleasePath
_release_sys.path.insert(0, str(_ReleasePath(__file__).resolve().parents[1]))
from backend.services.project_paths import native_parent
"""Explicit one-current-artifact API smoke; no retry or model dispatch."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import time
from uuid import uuid4


def main():
    project=Path(__file__).resolve().parents[1];sys.path.insert(0,str(project))
    from fastapi.testclient import TestClient
    from backend.main import create_app
    from backend.agent.config import AgentSettings
    from backend.orchestrator.workflow import Workflow
    from backend.services.storage import LocalStorage
    from backend.services.simulator_client import SimulatorConfig
    from backend.services.simulator_final_client import SimulatorFinalClient,SimulatorFinalRuntime
    from tests.agent_fakes import FakeSimulator
    storage=LocalStorage(project/'backend/storage')
    config=replace(SimulatorConfig.from_env(),root=native_parent(project)/'simulator_final')
    runtime=SimulatorFinalRuntime(config)
    native=SimulatorFinalClient(storage,runtime,root=config.root)
    job_id='512f8695-3e1e-4e0f-81ca-bac392ef50d8'
    artifact_id='7bdec2fd-a3dc-478e-b623-ca8ae448f44d'
    folder=project/'.cache/simulator-final-integration'/str(uuid4());folder.mkdir(parents=True)
    source=project/'.cache/simulator-final-audit/e25fdd9d-b8a8-498d-9963-256ac232c481/prediction/B_PR_03_0004/trajectory.npz'
    job_file=storage.artifact_path('jobs',job_id,'.json')
    before={str(file):hashlib.sha256(file.read_bytes()).hexdigest() for file in (source,job_file)}
    app=create_app(workflow=Workflow(storage),simulator=FakeSimulator(),current_vla_preview=native,preview_runtime=runtime,agent_settings=AgentSettings(enabled=False))
    result=dict(verdict='INTEGRATION_FAIL',model_calls=0,isaac_launches=0,output=str(folder))
    print(json.dumps(dict(phase='API_SMOKE_START',output=str(folder))),flush=True)
    with TestClient(app) as api:
        try:
            # Explicit offline preparation refreshes code fingerprints. It never
            # changes the original attempt/job/mask or calls a model.
            native.prepare(job_id=job_id,artifact_id=artifact_id,kind='robot')
            response=api.post('/api/simulator/robot-preview',json=dict(job_id=job_id,artifact_id=artifact_id,output_kind='prediction'))
            if response.status_code!=202:
                result.update(http_status=response.status_code,error_code=response.json().get('code'))
                print(json.dumps(result),flush=True);return
            result['isaac_launches']=1
            deadline=time.monotonic()+180;previous=None
            while time.monotonic()<deadline:
                status=api.get('/api/simulator/status').json()['current_preview']
                if status['state']!=previous:
                    print(json.dumps(dict(state=status['state'],status=(status.get('latest') or {}).get('status'))),flush=True);previous=status['state']
                if status['state']=='FAILED':break
                if status['state']=='READY' and status['latest']['status']=='SUCCEEDED':
                    frames=api.get('/api/simulator/current-preview/frames',params=dict(job_id=job_id,artifact_id=artifact_id))
                    result.update(status=status,frames=frames.json(),http_status=202)
                    result['frames_verified']=all(api.get(frame['url']).status_code==200 for frame in frames.json()['frames'])
                    result['verdict']='INTEGRATION_PASS' if result['frames_verified'] and len(frames.json()['frames'])==3 else 'INTEGRATION_FAIL'
                    break
                time.sleep(.5)
            result.update(source_unchanged=all(hashlib.sha256(Path(file).read_bytes()).hexdigest()==digest for file,digest in before.items()),native_session=str(runtime.session),error=runtime.error)
        finally:
            api.post('/api/simulator/stop')
            result.update(cleanup_complete=runtime.process is None and runtime.lease is None)
            (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({key:result.get(key) for key in ('verdict','isaac_launches','model_calls','frames_verified','source_unchanged','cleanup_complete','error','http_status','error_code')}),flush=True)


if __name__=='__main__':main()
