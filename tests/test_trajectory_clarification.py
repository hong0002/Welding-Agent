"""Native clarification A–I: fake native outputs, zero model/network calls."""
import json
import shutil

import pytest
from fastapi.testclient import TestClient

from backend.agent.config import AgentSettings
from backend.agent.context import workspace_summary
from backend.main import create_app
from backend.model_clients.native import read_json, sha256
from backend.model_clients.native_approval import pixel_hash
from backend.orchestrator.clarification import answer_direction, extract
from backend.orchestrator.state_machine import WorkflowError
from tests.agent_fakes import FakeRunner, FakeSimulator
from tests.test_agent import events
from tests.test_native_output_preview import factory, ready
from tests.test_guided_vla import save

QUESTION='표시된 이음선은 화면에서 세로로 보입니다. 이 선의 어느 끝에서 시작해 어느 끝으로 용접할까요?'


def clarification_output(directory, *, stage='refiner', question=QUESTION):
    if stage=='refiner':
        shutil.rmtree(directory/'iteration_001')
        (directory/'retrieval.json').unlink()
        save(directory/'refiner.json',dict(status='needs_clarification',clarification_question_ko=question,
            reasoning='HIDDEN_PRIVATE_ANALYSIS',assumptions=['PRIVATE_COT'],search_text='FULL_PRIVATE_PROMPT'))
    else:
        (directory/'iteration_001/plan.json').unlink()
        save(directory/'iteration_001/clarification.json',dict(status='needs_clarification',clarification_question_ko=question,
            reasoning='HIDDEN_PRIVATE_ANALYSIS'))


def start(factory, *, repeat=False, stage='refiner'):
    dirs=[]
    def transform(directory):
        dirs.append(directory)
        if repeat or len(dirs)==1:
            clarification_output(directory,stage=stage,question=QUESTION if len(dirs)==1 else '표시된 선의 방향을 어느 끝에서 시작할까요?')
    workflow,transport,calls=factory(rough_output_transform=transform,vertical=True)
    job=workflow.plan(ready(workflow).id)
    return workflow,transport,calls,job,dirs


def chat(client,sid,job,answer,expected=None):
    payload=dict(session_id=sid,job_id=str(job.id),message=answer)
    if expected:payload['clarification_id']=str(expected)
    return events(client.post('/api/agent/chat/stream',json=payload))


@pytest.mark.parametrize('stage',['refiner','planner'])
def test_a_native_question_persisted_and_assistant_shown_without_reasoning(factory,stage):
    workflow,transport,calls,job,_=start(factory,stage=stage)
    pending=job.trajectory_clarification
    assert job.planning_status=='NEEDS_CLARIFICATION' and job.state.value=='INSTRUCTION_READY'
    assert job.native_output.status=='PARTIAL_NATIVE_OUTPUT' and job.rough3d is None
    assert pending.question==QUESTION and pending.stage==stage
    assert workspace_summary(job)['clarification_required']
    record=read_json(workflow.storage.artifact_path('native_context',pending.id,'.clarification.json'))
    assert record['approved_mask_hash']==pixel_hash(workflow.storage.read_image('masks',job.mask.id))
    assert record['original_instruction']=='왼쪽에서 오른쪽으로 용접해'
    with pytest.raises(WorkflowError):workflow.plan(job.id)
    with pytest.raises(Exception):workflow.run_guided_vla(job.id)
    runner=FakeRunner();simulator=FakeSimulator()
    app=create_app(workflow=workflow,simulator=simulator,agent_runner=runner,agent_settings=AgentSettings(api_key='offline-test'))
    with TestClient(app) as client:
        sid=client.post('/api/agent/sessions').json()['session_id']
        output=chat(client,sid,job,'경로 만들어줘')
        text=next(data['text'] for event,data in output if event=='assistant_delta')
        assert QUESTION in text and '위에서 아래로' in text
        assert not any(e=='error' for e,_ in output)
        assert all(term not in json.dumps(output,ensure_ascii=False) for term in ('PRIVATE','HIDDEN','FULL_PRIVATE','D:\\','/refiner.json'))
    assert runner.calls==0 and len(calls['rough3d'])==1 and not simulator.calls and not transport.calls


@pytest.mark.parametrize('answer,direction',[
    ('위에서 아래로','top_to_bottom'),('위쪽 끝에서 시작해서 아래로','top_to_bottom'),('아래에서 위로','bottom_to_top')])
def test_b_c_d_e_f_explicit_reply_t3_only_reuses_exact_approval_and_validates(factory,answer,direction):
    workflow,transport,calls,job,dirs=start(factory)
    mask=job.mask.model_dump(mode='json');mask_path=workflow.storage.artifact_path('masks',job.mask.id)
    mask_hash=sha256(mask_path);approval_file_hash=sha256(workflow.storage.artifact_path('masks',job.mask.id,'.json'))
    pending=job.trajectory_clarification;record_path=workflow.storage.artifact_path('native_context',pending.id,'.clarification.json')
    old={p.relative_to(dirs[0]).as_posix():sha256(p) for p in dirs[0].rglob('*') if p.is_file()}
    record_hash=sha256(record_path)
    runner=FakeRunner();simulator=FakeSimulator()
    app=create_app(workflow=workflow,simulator=simulator,agent_runner=runner,agent_settings=AgentSettings(api_key='offline-test'))
    with TestClient(app) as client:
        sid=client.post('/api/agent/sessions').json()['session_id']
        output=chat(client,sid,job,answer,pending.id)
        assert next(d for e,d in output if e=='done')['ok']
        result=client.get(f'/api/weld/{job.id}').json()
        assert result['state']=='ROUGH_PATH_READY' and result['planning_status']=='READY'
        assert result['trajectory_clarification'] is None and result['rough3d']
        assert result['mask']==mask
        assert result['instruction']['structured']['direction']==direction
        resolved=result['instruction']['text']
        assert '왼쪽' not in resolved and '오른쪽' not in resolved and '위쪽' in resolved and '아래쪽' in resolved
        assert '--instruction='+resolved in calls['rough3d'][-1]
        assert not any('top_to_bottom' in a or 'bottom_to_top' in a for a in calls['rough3d'][-1])
        # Consumed/stale quick replies cannot execute an extra attempt.
        stale=chat(client,sid,job,answer,pending.id)
        assert next(d for e,d in stale if e=='done')['ok'] is False
    receipt=read_json(workflow.storage.artifact_path('native_context',pending.id,'.clarification-answer.json'))
    assert receipt['original_instruction']=='왼쪽에서 오른쪽으로 용접해'
    assert receipt['clarification_answer']==answer and receipt['resolved_instruction']==resolved
    assert sha256(mask_path)==mask_hash and sha256(record_path)==record_hash
    assert sha256(workflow.storage.artifact_path('masks',job.mask.id,'.json'))==approval_file_hash
    assert old=={p.relative_to(dirs[0]).as_posix():sha256(p) for p in dirs[0].rglob('*') if p.is_file()}
    assert len(dirs)==2 and dirs[0]!=dirs[1]
    assert len(calls['segment'])==1 and len(calls['rough3d'])==2
    assert runner.calls==0 and not transport.calls and transport.health_calls==0 and not simulator.calls


def test_g_repeat_question_new_identity_no_auto_retry(factory):
    workflow,transport,calls,job,dirs=start(factory,repeat=True)
    original=job.trajectory_clarification
    result=workflow.answer_trajectory_clarification(job.id,original.id,'위에서 아래로')
    assert result.planning_status=='NEEDS_CLARIFICATION'
    assert result.trajectory_clarification.id!=original.id
    assert result.trajectory_clarification.question!=QUESTION
    assert len(calls['rough3d'])==2 and len(dirs)==2 and not transport.calls
    next_record=read_json(workflow.storage.artifact_path('native_context',result.trajectory_clarification.id,'.clarification.json'))
    assert next_record['original_instruction']=='왼쪽에서 오른쪽으로 용접해'
    with pytest.raises(WorkflowError):workflow.answer_trajectory_clarification(job.id,original.id,'아래에서 위로')


@pytest.mark.parametrize('answer',['그쪽으로','알아서','위에서 아래로 아니면 아래에서 위로','위에서 아래로 하지마','Guided VLA 실행해','경로 다시 생성해'])
def test_h_ambiguous_does_not_run_any_model(factory,answer):
    workflow,_,calls,job,_=start(factory)
    before=job.model_dump(mode='json')
    result=workflow.answer_trajectory_clarification(job.id,job.trajectory_clarification.id,answer)
    assert result.model_dump(mode='json')==before and len(calls['rough3d'])==1
    assert not workflow.storage.artifact_path('native_context',job.trajectory_clarification.id,'.clarification-answer.json').exists()


def test_legacy_partial_backfill_preserves_original_proof_and_never_reruns(factory):
    workflow,_,calls,job,_=start(factory)
    proof_path=workflow.storage.artifact_path('native_context',job.native_output.native_artifact_id,'.native-output.json')
    old_proof=sha256(proof_path);old_output=job.native_output.model_dump_json()
    job.trajectory_clarification=None;job.planning_status='NOT_READY';workflow.storage.save_job(job)
    restored=workflow.get_job(job.id)
    assert restored.trajectory_clarification.question==QUESTION
    assert restored.native_output.model_dump_json()==old_output and sha256(proof_path)==old_proof
    assert workflow.get_job(job.id).trajectory_clarification.id==restored.trajectory_clarification.id
    assert len(calls['rough3d'])==1


def test_upstream_edit_cancels_pending_and_rejects_stale_reply(factory):
    workflow,_,calls,job,_=start(factory)
    pending=job.trajectory_clarification
    workflow.parse_instruction(job.id,'오른쪽에서 왼쪽으로 용접해')
    assert workflow.get_job(job.id).trajectory_clarification is None
    with pytest.raises(WorkflowError):workflow.answer_trajectory_clarification(job.id,pending.id,'위에서 아래로')
    assert len(calls['rough3d'])==1


def test_new_user_instruction_starts_new_original_provenance(factory):
    workflow,_,_,job,_=start(factory,repeat=True)
    job=workflow.answer_trajectory_clarification(job.id,job.trajectory_clarification.id,'위에서 아래로')
    job=workflow.parse_instruction(job.id,'오른쪽에서 왼쪽으로 용접해')
    job=workflow.plan(job.id)
    record=read_json(workflow.storage.artifact_path('native_context',job.trajectory_clarification.id,'.clarification.json'))
    assert record['original_instruction']=='오른쪽에서 왼쪽으로 용접해'


def test_pending_tamper_rejected_before_attempt(factory):
    workflow,_,calls,job,_=start(factory)
    job.trajectory_clarification.question='changed';workflow.storage.save_job(job)
    with pytest.raises(WorkflowError):workflow.get_job(job.id)
    assert len(calls['rough3d'])==1


@pytest.mark.parametrize('stage,question',[
    ('refiner','화면에서 이음선이 세로로 보입니다. 이음선을 따라 위에서 아래로 용접할까요, 아래에서 위로 용접할까요?'),
    ('planner','F 영상에서 이음선의 위쪽 끝에서 아래쪽 끝으로 진행할까요, 아니면 아래쪽 끝에서 위쪽 끝으로 진행할까요?')])
def test_real_native_wording_and_arrow_reply_resolve_without_keyword_guard(factory,stage,question):
    directories=[]
    def transform(directory):
        directories.append(directory)
        if len(directories)==1:clarification_output(directory,stage=stage,question=question)
    workflow,transport,calls=factory(rough_output_transform=transform,vertical=True)
    job=workflow.plan(ready(workflow).id);pending=job.trajectory_clarification
    mask=job.mask.model_dump(mode='json');mask_hash=sha256(workflow.storage.artifact_path('masks',job.mask.id))
    source=sha256(workflow.storage.artifact_path('native_context',pending.id,'.clarification.json'))
    run=workflow.rough3d.runtime.run
    def observed(*args,**kwargs):
        ctx=workflow.storage.root/'native_context'
        claims=list(ctx.glob(f'{pending.id}.*.clarification-claim.json'))
        assert len(claims)==1 and read_json(claims[0])['status']=='claimed'
        assert not workflow.storage.artifact_path('native_context',pending.id,'.clarification-answer.json').exists()
        current=workflow.storage.get_job(job.id)
        assert current.trajectory_clarification.id==pending.id and current.instruction.text==job.instruction.text
        return run(*args,**kwargs)
    workflow.rough3d.runtime.run=observed
    result=workflow.answer_trajectory_clarification(job.id,pending.id,'위 → 아래')
    assert result.state.value=='ROUGH_PATH_READY' and result.trajectory_clarification is None
    assert result.instruction.text=='표시된 이음선의 위쪽 끝에서 시작하여 아래쪽 끝으로 용접한다.'
    assert result.instruction.structured.direction=='top_to_bottom'
    assert result.instruction.structured.region_order==job.instruction.structured.region_order
    assert result.mask.model_dump(mode='json')==mask and sha256(workflow.storage.artifact_path('masks',job.mask.id))==mask_hash
    assert sha256(workflow.storage.artifact_path('native_context',pending.id,'.clarification.json'))==source
    receipt=read_json(workflow.storage.artifact_path('native_context',pending.id,'.clarification-answer.json'))
    assert receipt['status']=='consumed'
    assert len(calls['segment'])==1 and len(calls['rough3d'])==2 and not transport.calls


@pytest.mark.parametrize('failure,code',[
    ('admission','TRAJECTORY3_ADMISSION_FAILED'),('native','TRAJECTORY3_NATIVE_FAILED'),
    ('timeout','TRAJECTORY3_TIMEOUT'),('invalid','TRAJECTORY3_OUTPUT_INVALID')])
def test_failed_reply_keeps_pending_and_explicit_resubmission_is_safe(factory,failure,code):
    from backend.model_clients.contracts import ModelFault
    from backend.orchestrator.clarification import ClarificationError
    from subprocess import TimeoutExpired
    workflow,transport,calls,job,_=start(factory)
    pending=job.trajectory_clarification;original=job.model_dump(mode='json')
    runtime=workflow.rough3d.runtime;run=runtime.run
    prepare=workflow.rough3d.approvals.prepare
    if failure=='admission':
        def fail(*args,**kwargs):raise ModelFault('NATIVE_INPUT_MISMATCH')
        workflow.rough3d.approvals.prepare=fail
    else:
        def fail(*args,**kwargs):
            result=run(*args,**kwargs)
            if failure=='timeout':raise TimeoutExpired('offline-native-fixture',1)
            if failure=='native':return 3,[]
            from pathlib import Path
            directory=Path(result[1][0]).parent.parent
            save(directory/'query_image_guidance_2d.json',{})
            return result
        runtime.run=fail
    with pytest.raises(ClarificationError) as error:
        workflow.answer_trajectory_clarification(job.id,pending.id,'위에서 아래로')
    assert error.value.code==code
    restored=workflow.get_job(job.id)
    assert restored.model_dump(mode='json')==original
    assert not workflow.storage.artifact_path('native_context',pending.id,'.clarification-answer.json').exists()
    ctx=workflow.storage.root/'native_context'
    claims=list(ctx.glob(f'{pending.id}.*.clarification-claim.json'))
    assert len(claims)==1
    outcome=read_json(claims[0].with_name(claims[0].name.replace('.clarification-claim.json','.clarification-outcome.json')))
    assert outcome['status']=='failed' and outcome['retryable'] and outcome['reason_code']==code
    old_claim=sha256(claims[0]);before=len(calls['rough3d'])
    runtime.run=run;workflow.rough3d.approvals.prepare=prepare
    result=workflow.answer_trajectory_clarification(job.id,pending.id,'위에서 아래로')
    assert result.state.value=='ROUGH_PATH_READY'
    assert len(calls['rough3d'])==before+1 and len(calls['segment'])==1 and not transport.calls
    assert sha256(claims[0])==old_claim and len(list(ctx.glob(f'{pending.id}.*.clarification-claim.json')))==2


def test_approval_changed_has_safe_code_and_zero_native_dispatch(factory):
    from datetime import timedelta
    workflow,_,calls,job,_=start(factory)
    pending=job.trajectory_clarification
    job.mask.approved_at+=timedelta(seconds=1)
    workflow.storage.save_job(job)
    runner=FakeRunner();simulator=FakeSimulator()
    app=create_app(workflow=workflow,simulator=simulator,agent_runner=runner,agent_settings=AgentSettings(api_key='offline-test'))
    with TestClient(app) as client:
        sid=client.post('/api/agent/sessions').json()['session_id']
        response=client.post('/api/agent/chat/stream',json=dict(session_id=sid,job_id=str(job.id),
            clarification_id=str(pending.id),message='위에서 아래로'))
        assert response.status_code==409 and response.json()['code']=='APPROVAL_CHANGED'
        assert all(term not in response.text for term in ('HIDDEN','PRIVATE','D:\\','sha256'))
    assert len(calls['rough3d'])==1 and runner.calls==0 and not simulator.calls


def test_unsettled_claim_blocks_another_reply_without_consuming(factory):
    from uuid import uuid4
    from backend.orchestrator.clarification import ClarificationError
    workflow,_,calls,job,_=start(factory);pending=job.trajectory_clarification
    ctx=workflow.storage.root/'native_context'
    save(ctx/f'{pending.id}.{uuid4()}.clarification-claim.json',dict(status='claimed'))
    with pytest.raises(ClarificationError) as error:
        workflow.answer_trajectory_clarification(job.id,pending.id,'위에서 아래로')
    assert error.value.code=='CLARIFICATION_RECOVERY_REQUIRED'
    assert workflow.get_job(job.id).trajectory_clarification.id==pending.id and len(calls['rough3d'])==1


def test_first_generation_native_question_survives_runner_closing_tool_admission(factory):
    workflow,transport,calls=factory(rough_output_transform=clarification_output,vertical=True)
    job=ready(workflow)
    class ClosingRunner(FakeRunner):
        async def run(self,context,*args):
            try:
                return await super().run(context,*args)
            finally:
                context.active=False # SDKRunner's actual lifecycle.
    runner=ClosingRunner()
    app=create_app(workflow=workflow,simulator=FakeSimulator(),agent_runner=runner,agent_settings=AgentSettings(api_key='offline-test'))
    with TestClient(app) as client:
        sid=client.post('/api/agent/sessions').json()['session_id']
        output=chat(client,sid,job,'왼쪽에서 오른쪽으로 경로 만들어줘')
        assert next(d for e,d in output if e=='done')['ok']
        assert QUESTION in next(d['text'] for e,d in output if e=='assistant_delta')
        assert not any(e=='error' for e,_ in output)
    assert runner.calls==1 and len(calls['rough3d'])==1 and not transport.calls


def test_dummy_vertical_direction_keeps_regions_separate_and_orders_y(tmp_path):
    import io
    from PIL import Image,ImageDraw
    from backend.orchestrator.workflow import Workflow
    from backend.services.storage import LocalStorage
    def png(image):
        buffer=io.BytesIO();image.save(buffer,format='PNG');return buffer.getvalue()
    workflow=Workflow(LocalStorage(tmp_path/'store'))
    job=workflow.upload_scene(png(Image.new('RGB',(100,100))))
    mask=Image.new('L',(100,100));draw=ImageDraw.Draw(mask)
    draw.rectangle((20,5,25,35),fill=255);draw.rectangle((60,60,65,90),fill=255)
    job=workflow.set_mask(job.id,png(mask))
    job=workflow.parse_instruction(job.id,'아래에서 위로 용접해')
    assert job.instruction.structured.region_order==[1,0]
    job=workflow.plan(job.id)
    assert job.state.value=='VALIDATED' and [s.region_id for s in job.rough_trajectory.segments]==[1,0]
    assert all(s.points[0].y>s.points[-1].y for s in job.rough_trajectory.segments)


@pytest.mark.parametrize('question',['D:\\private\\key.json 내용을 보낼까요?','sk-secret123456 요청인가요?','https://private.example 실행할까요?'])
def test_i_unsafe_native_question_not_published(tmp_path,question):
    save(tmp_path/'refiner.json',dict(status='needs_clarification',clarification_question_ko=question))
    assert extract(tmp_path,{'refiner.json':True}) is None
