"""Explicit READ-ONLY B_PR artifact replay. Never invokes processes or HTTP.

Not the default test factory. Replays prior successful outputs through the real
normalizers, immutable approved-mask adapter and Guided request/response boundary.
Only new Welding-Agent-owned storage and approval sessions are written.
"""
from dataclasses import replace
from pathlib import Path
from uuid import uuid4
import json
import numpy as np
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.model_clients.config import ROOT, ModelSettings
from backend.model_clients.contracts import ModelFault
from backend.model_clients.factory import configured_rough3d_client
from backend.model_clients.guided_vla import GuidedVLASettings
from backend.model_clients.guided_workflow import WorkflowGuidedVLAClient
from backend.model_clients.native import NativeRuntime, NativeResult, NativeSegmentClient, read_json, read_native_result, sha256, accepted_session
from backend.model_clients.native_rough3d import NativeRough3DClient
from backend.orchestrator.workflow import Workflow
from backend.services.scene_dataset import DatasetScenes
from backend.services.storage import LocalStorage
from backend.orchestrator.instruction_parser import DummyInstructionParser
from backend.schemas import StructuredInstruction
from tests.agent_fakes import FakeSimulator
from tests.module_fakes import OfflineGuided

SAMPLE = 'B_PR_03_0001'
SOURCE_ATTEMPT = ROOT/'.cache/native-models/guided-vla/866654a5-8cc7-4edc-82a8-0c276818aad8'
SOURCE_SEGMENT = ROOT/'.cache/native-models/47300c47-24f5-4714-a480-02b732b5365b.json'


class ReplayRuntime(NativeRuntime):
    def __init__(self, settings, records, directory, artifact_id, source_sha256):
        super().__init__(settings, records=records, run=self.forbidden_process)
        self.directory = directory
        self.artifact_id = artifact_id
        self.source_sha256 = source_sha256
        self.dispatches = 0

    @staticmethod
    def forbidden_process(*args, **kwargs):
        raise AssertionError('Replay must never start a native process')

    def execute(self, *, sample_id, instruction, views=None, mask_session=None):
        if sample_id != SAMPLE or views is not None:raise ModelFault('NATIVE_INPUT_MISMATCH')
        if self.settings.stage == 'rough3d':
            _, accepted = accepted_session(mask_session)
            if accepted['sample_id'] != SAMPLE:raise ModelFault('NATIVE_INPUT_MISMATCH')
        config, _, _ = self.configuration()
        data = read_native_result(self.settings.stage, self.directory, sample_id, instruction)
        self.dispatches += 1
        self.verified = True
        return NativeResult(self.directory,self.artifact_id,data,config,0,self.source_sha256)


def replay_workflow(root):
    root = Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    records = root/'records';records.mkdir(exist_ok=True)
    original = read_json(SOURCE_SEGMENT);segment_dir = Path(original['directory'])
    assert all(sha256(segment_dir/name)==expected for name,expected in original['files'].items())
    (records/SOURCE_SEGMENT.name).write_bytes(SOURCE_SEGMENT.read_bytes())
    manifest = read_json(SOURCE_ATTEMPT/'request_manifest.json')
    assert all(sha256(SOURCE_ATTEMPT/name)==expected for name,expected in manifest['files'].items())
    rough_dir = Path(manifest['rough_session'])
    assert all(sha256(rough_dir/name)==expected for name,expected in manifest['rough_source_files'].items())
    segment_settings = ModelSettings.from_env('segment')
    # Test factory may force Dummy globally; the replay boundary itself never launches.
    segment_settings = replace(segment_settings,backend='native')
    segment = NativeSegmentClient(ReplayRuntime(segment_settings,records,segment_dir,
        original['artifact_id'],original['source_sha256']))
    rough_settings = configured_rough3d_client().runtime.settings
    rough = NativeRough3DClient(ReplayRuntime(rough_settings,records,rough_dir,str(uuid4()),
        sha256(rough_dir/'iteration_001/plan.json')))
    source_plan=read_json(rough_dir/'iteration_001/plan.json')
    class ReplayParser(DummyInstructionParser):
        def parse(self,text):
            if text==source_plan['raw_instruction_ko']:
                direction='right_to_left' if source_plan['plan']['segment_decisions'][0]['direction']=='reverse' else 'left_to_right'
                return StructuredInstruction(direction=direction)
            return super().parse(text)
    response = read_json(SOURCE_ATTEMPT/'response.json')
    class ReplayGuided(OfflineGuided):
        def health(self):
            # Readiness is a fixture, not evidence about the current live server.
            # A missing original model name must remain unavailable.
            return {'status':'ready','waypoints':9,'dimensions':3}
    transport = ReplayGuided(response)
    guided = WorkflowGuidedVLAClient(GuidedVLASettings(api_token='',attempts=root/'guided-vla'),transport=transport)
    workflow = Workflow(LocalStorage(root/'storage'),dataset=DatasetScenes.configured(),parser=ReplayParser(),
        segmentation=segment,rough3d=rough,guided_vla=guided)
    return workflow,transport,manifest


def main():
    root = ROOT/'.cache/module-integration-e2e'/str(uuid4())
    workflow,transport,manifest = replay_workflow(root)
    source_result = read_json(workflow.segmentation.runtime.directory/'iteration_001/result.json')
    source_plan = read_json(workflow.rough3d.runtime.directory/'iteration_001/plan.json')
    with TestClient(create_app(workflow=workflow,simulator=FakeSimulator())) as client:
        loaded = client.post('/api/scenes/sample',json={'sample_id':SAMPLE});assert loaded.status_code==201
        job = loaded.json();jid = job['id']
        segmented = client.post('/api/masks/automatic',json={'job_id':jid,'instruction':source_result['instruction']})
        assert segmented.status_code==200,segmented.text
        job = segmented.json()
        approved = client.post('/api/masks/approve',json={'job_id':jid,'mask_id':job['mask']['id'],'view_id':'F'})
        assert approved.status_code==200
        parsed = client.post('/api/instructions/parse',json={'job_id':jid,'instruction':source_plan['raw_instruction_ko']})
        assert parsed.status_code==200
        rough = client.post('/api/weld/plan',json={'job_id':jid});assert rough.status_code==200,rough.text
        ready = client.post(f'/api/weld/{jid}/guided-vla',json={});assert ready.status_code==200,ready.text
        job = ready.json();assert job['state']=='VLA_READY'
        assert len(transport.calls)==1 and job['vla_prediction']['mask_views']==['F']
        assert client.get('/api/simulator/status').json()['state']=='STOPPED'
    attempt=workflow.guided_vla.settings.attempts/job['vla_prediction']['attempt_id']
    with np.load(SOURCE_ATTEMPT/'trajectory.npz',allow_pickle=False) as original, np.load(attempt/'trajectory.npz',allow_pickle=False) as replay:
        for name in ('predicted_path_m','ground_truth_path_m'):np.testing.assert_array_equal(original[name],replay[name])
    assert all(sha256(SOURCE_ATTEMPT/name)==expected for name,expected in manifest['files'].items())
    assert all(sha256(Path(manifest['rough_session'])/name)==expected for name,expected in manifest['rough_source_files'].items())
    report = dict(verdict='MODULE_ARTIFACT_REPLAY_PASS',sample_id=SAMPLE,job_id=jid,
        views=list(job['scene']['views']),mask_views=[v for v,m in job['scene']['views'].items() if m['mask']],
        approved_views=[v for v,m in job['scene']['views'].items() if m['mask'] and m['mask']['approved']],
        state=job['state'],rough3d=job['rough3d'],vla=job['vla_prediction'],
        source_attempt=SOURCE_ATTEMPT.name,source_segment_artifact=original_id(),
        source_artifacts_preserved=True,model_calls=0,network_calls=0,simulator_calls=0,
        fixture_gate='B_PR_TOOL_CLEARANCE_FAIL',simulator_ready=False)
    (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'verdict':report['verdict'],'report':str(root/'report.json'),'state':job['state'],'calls':0}))


def original_id():return read_json(SOURCE_SEGMENT)['artifact_id']


if __name__=='__main__':main()
