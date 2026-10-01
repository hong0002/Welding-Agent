"""Explicit one-shot migration smoke. No retries, Guided HTTP, Runner or simulator.

The claim is permanent so accidentally invoking this command again cannot launch
another expensive migration run. All models/config/cwd/sample are backend-owned.
"""
import argparse
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from uuid import UUID, uuid4

from backend.agent.config import AgentSettings
from backend.agent.service import AgentService
from backend.model_clients.config import ROOT, ModelSettings
from backend.model_clients.guided_vla import GuidedVLASettings, write_json
from backend.model_clients.guided_workflow import WorkflowGuidedVLAClient
from backend.model_clients.integrity import source_digest
from backend.model_clients.native import (CAMERAS, NATIVE_PYTHON, NativeRuntime,
    NativeSegmentV2Client, read_json, sha256)
from backend.model_clients.native_rough3d import NativeRough3DV3Client, NativeRough3DClient
from backend.native_stack_windows import DATASET
from backend.orchestrator.state_machine import WorkflowError
from backend.orchestrator.workflow import Workflow
from backend.schemas import StructuredInstruction
from backend.services.scene_dataset import DatasetScenes
from backend.services.storage import LocalStorage

SAMPLE = 'B_PR_03_0001'


class ForbiddenExternal:
    def __getattr__(self, name):
        raise AssertionError('External Runner/Guided/Simulator action forbidden')

    async def run(self, *args, **kwargs):
        raise AssertionError('Orchestrator model call forbidden in migration smoke')

    def post(self, *args, **kwargs):
        raise AssertionError('Guided VLA HTTP forbidden in migration smoke')

    def health(self):
        raise AssertionError('Guided VLA health probe forbidden in migration smoke')


def preserved_sources():
    return {name: source_digest(ROOT.parent/name) for name in
        ('vlm_segment', 'vlm_segment2', 'vlm_trajectory2', 'vlm_trajectory3')}


def settings(stage):
    config = ROOT/'.cache/native-integration/configs'
    return ModelSettings(stage=stage, backend='native_v2' if stage == 'segment' else 'native_3d_v3',
        repository=ROOT.parent/('vlm_segment2' if stage == 'segment' else 'vlm_trajectory3'),
        python=NATIVE_PYTHON, native_config=config/('segment2.windows.yaml' if stage == 'segment' else 'trajectory3.windows.yaml'),
        native_binding=config/'binding.json', timeout=900, reference_mode='native')


def build_workflow(directory):
    # Shared records are required for immutable approved-session lineage.
    records=ROOT/'.cache/native-models'
    return Workflow(LocalStorage(directory/'storage'), dataset=DatasetScenes(DATASET),
        segmentation=NativeSegmentV2Client(NativeRuntime(settings('segment'), records=records)),
        rough3d=NativeRough3DV3Client(NativeRuntime(settings('rough3d'), records=records)),
        guided_vla=WorkflowGuidedVLAClient(
            GuidedVLASettings(server_url=GuidedVLASettings.from_env().server_url,
                              attempts=directory/'guided-attempts'),
            transport=ForbiddenExternal()))


async def chat(agent, sid, job_id, message):
    queue=await agent.begin(sid, job_id, message)
    events=[]
    while True:
        event,data=await queue.get()
        events.append({'event':event, **data})
        if event == 'done':
            if not data['ok']:
                code=next((e.get('code') for e in events if e['event']=='error'), 'AGENT_MASK_WORKFLOW_FAIL')
                raise WorkflowError(code)
            return events, UUID(data['job_id'])


async def run(directory, workflow):
    report={'sample_id':SAMPLE, 'segment_claimed':False, 'trajectory_claimed':False,
            'guided_prediction_calls':0, 'orchestrator_model_calls':0, 'simulator_calls':0,
            'gates':{}, 'phase':'preflight', 'source_before':preserved_sources()}
    agent=None
    def milestone(phase, **values):
        report['phase']=phase
        report.update(values)
        with (directory/'milestones.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps({'at_utc':datetime.now(timezone.utc).isoformat(),
                'phase':phase, **values},ensure_ascii=False)+'\n')
        print(phase, flush=True)
    try:
        workflow.segmentation.runtime.configuration()
        workflow.rough3d.runtime.configuration()
        report['config_hashes']={s:sha256(settings(s).native_config) for s in ('segment','rough3d')}
        agent=AgentService(workflow, ForbiddenExternal(), runner=ForbiddenExternal(),
            settings=AgentSettings(api_key='explicit-offline-router',run_timeout=1000))
        sid=agent.sessions.create()
        _,job_id=await chat(agent,sid,None,SAMPLE+' 불러와')
        job=workflow.get_job(job_id)
        if list(job.scene.views) != list(CAMERAS):raise ValueError('Nine-view scene differs')
        milestone('scene_ready',job_id=str(job_id),split=job.scene.split,views=list(job.scene.views))
        write_json(directory/'segment.claim.json',{'sample_id':SAMPLE,'retry':False})
        milestone('segment_started',segment_claimed=True)
        start=time.monotonic()
        events,_=await chat(agent,sid,job_id,'용접할 부분 찾아줘')
        names=[e['tool'] for e in events if e['event']=='tool_started']
        if names != ['get_workspace_state','detect_weld_mask']:raise ValueError('Mask routing differs')
        write_json(directory/'agent-mask-events.json',events) # sanitized public SSE only
        job=workflow.get_job(job_id)
        mask_views=[v for v,s in job.scene.views.items() if s.mask]
        if mask_views != ['F','R','S4'] or any(job.scene.views[v].mask.approved for v in mask_views):
            raise ValueError('Native mask views/approval differ')
        source_id=job.mask.artifact.provenance.native_source_artifact_id
        source=read_json(workflow.segmentation.runtime.records/f'{source_id}.json')
        detection=read_json(Path(source['directory'])/'yolo/detections.json')
        if detection['sample_id'] != SAMPLE or detection['bbox_source'] != 'server_yolo':
            raise ValueError('Segment2 native detection differs')
        report['gates'].update(SEGMENT2_NATIVE_PASS=True,AGENT_MASK_WORKFLOW_PASS=True)
        milestone('segment_pass',segment_seconds=round(time.monotonic()-start,3),
            segment_session=source['directory'],segment_diagnostic=workflow.segmentation.runtime.last_diagnostic_id,
            mask_views=mask_views,mask_id=str(job.mask.id),region_count=len(job.mask.regions))
        try:
            workflow.apply_instruction(job_id,'왼쪽에서 오른쪽으로 용접해',StructuredInstruction(direction='left_to_right'))
        except WorkflowError:
            pass
        else:
            raise ValueError('Unapproved mask allowed planning')
        # User explicitly authorized this smoke confirmation, separate from Agent.
        job=workflow.approve_mask(job_id,job.mask.id,'F')
        write_json(directory/'smoke-approval.json',{'source':'explicit_user_authorized_smoke',
            'mask_id':str(job.mask.id),'approved_at':job.mask.approved_at.isoformat(),
            'mask_sha256':sha256(workflow.storage.artifact_path('masks',job.mask.id))})
        report['gates']['HUMAN_APPROVAL_PASS']=True
        milestone('smoke_F_approved')
        workflow.apply_instruction(job_id,'왼쪽에서 오른쪽으로 용접해',
            StructuredInstruction(direction='left_to_right'),parser='explicit-smoke-direction')
        write_json(directory/'trajectory.claim.json',{'sample_id':SAMPLE,'retry':False})
        milestone('trajectory_started',trajectory_claimed=True)
        start=time.monotonic()
        job=await asyncio.to_thread(workflow.plan,job_id)
        record=read_json(workflow.storage.artifact_path('native_context',job.rough3d.artifact_id,'.rough3d.json'))
        rough=NativeRough3DClient.load_saved(record['directory'],SAMPLE,version='native_3d_v3')
        if rough.native_stack != 'vlm_trajectory3' or job.state.value != 'ROUGH_PATH_READY':
            raise ValueError('Native Trajectory3 workflow differs')
        if rough.reference_trajectory_3d.registered_to_query or job.rough3d.reference_in_request:
            raise ValueError('Reference registration/request differs')
        native_plan=read_json(rough.directory/'iteration_001/plan.json')
        report['gates']['TRAJECTORY3_NATIVE_PASS']=True
        milestone('trajectory_pass',trajectory_seconds=round(time.monotonic()-start,3),
            trajectory_session=record['directory'],trajectory_diagnostic=workflow.rough3d.runtime.last_diagnostic_id,
            point_count=sum(len(s['points_normalized']) for s in rough.image_guidance_2d['segments']),
            approved_session=native_plan['previous_mask_session'],yolo_request_id=native_plan['yolo_request_id'])
        attempt=workflow.guided_vla.prepare_workflow(workflow.storage,job)
        manifest,_=workflow.guided_vla.verify(attempt)
        if manifest['live_called'] or manifest['reference_in_request'] or (attempt/'submission.json').exists():
            raise ValueError('Guided package consumed or contains reference')
        report['gates']['GUIDED_VLA_INPUT_COMPAT_PASS']=True
        milestone('guided_package_offline_pass',guided_attempt=str(attempt),manifest_sha256=sha256(attempt/'request_manifest.json'),
                  reference_in_request=False,live_called=False)
        report['verdict']='LIVE_NATIVE_STACK_PASS'
    except Exception as exc:
        report['verdict']='SEGMENT2_LIVE_FAIL' if not report['gates'].get('SEGMENT2_NATIVE_PASS') else (
            'TRAJECTORY3_LIVE_FAIL' if not report['gates'].get('TRAJECTORY3_NATIVE_PASS') else 'GUIDED_VLA_INPUT_INCOMPATIBLE')
        # Only exception class and stable backend code. No arbitrary exception body.
        report['error_class']=type(exc).__name__
        report['error_code']=getattr(exc,'code',None)
        print(report['verdict'],flush=True)
    finally:
        if agent:await agent.close()
        report['source_after']=preserved_sources()
        report['external_sources_unchanged']=report['source_before']==report['source_after']
        report['diagnostics']={s:getattr(getattr(workflow.segmentation if s=='segment' else workflow.rough3d,'runtime',None),'last_diagnostic_id',None)
                               for s in ('segment','rough3d')}
        write_json(directory/'report.json',report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    args=parser.parse_args()
    if not args.live:parser.error('Explicit --live required')
    parent=ROOT/'.cache/native-integration/migration-live'
    parent.mkdir(parents=True,exist_ok=True)
    run_id=str(uuid4())
    write_json(parent/'one-shot.claim.json',{'run_id':run_id,'sample_id':SAMPLE,'auto_retry':False})
    directory=parent/run_id
    directory.mkdir(exist_ok=False)
    print('RUN_ID='+run_id,flush=True)
    report=asyncio.run(run(directory,build_workflow(directory)))
    print('REPORT='+str(directory/'report.json'),flush=True)
    raise SystemExit(0 if report['verdict']=='LIVE_NATIVE_STACK_PASS' and report['external_sources_unchanged'] else 1)


if __name__ == '__main__':
    main()
