"""Intent, admission and display events using fake native/HTTP outputs only."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.agent.config import AgentSettings
from backend.agent.context import WeldingAgentContext
from backend.agent.decision import AgentDecisionSummary, DecisionIntent, parse_request
from backend.main import create_app
from backend.model_clients.native import read_json
from tests.agent_fakes import FakeRunner, FakeSimulator, invoke
from tests.native_stack_fakes import candidate_workflow
from tests.test_agent import events
from tests.test_module_workflow import rough_job


POSITIVE = ['Guided VLA 실행해줘','VLA 실행해줘','VLA로 실제 궤적 생성해줘','VLA로 궤적 만들어줘',
    'VLA로 최종 궤적 만들어줘','VLA로 최종 경로 예측해줘','실제 3D 궤적 생성해줘',
    '최종 3D 궤적 만들어줘','최종 3D 경로 생성해줘','최종 3D 경로 예측해줘',
    '로봇용 3D 궤적 예측해줘','최종 XYZ 경로 만들어줘','VLA 결과 생성해줘',
    '실제 궤적 뽑아줘','실제 궤적 생성해줘','최종 궤적 예측해줘',
    'run VLA','run Guided VLA','generate the final VLA trajectory',
    'generate the 3D trajectory with VLA','predict the final 3D path']
NEGATIVE = ['VLA가 뭐야?','Guided VLA 설명해줘','VLA 성능 어때?','VLA 결과가 왜 이래?',
    'VLA 실행할 수 있어?','VLA 실행하지 마','VLA는 나중에 돌리자','지금 VLA가 준비됐어?',
    'VLA 서버 상태 확인해줘','VLA 결과를 보여줘','기존 VLA 결과 설명해줘',
    "Don't run Guided VLA",'Explain how to run VLA','Can you run VLA?',
    'VLA','궤적','실제','VLA 생성 방법 설명해줘','VLA 서버 실행해줘',
    'VLA 생성 후 시뮬레이터까지 보여줘 하지 마','VLA 생성 후 시뮬레이터까지 보여줄 수 있어?',
    'VLA 실행하면 안돼','VLA 실행하지 않아']
SIMULATOR = ['VLA 경로 시뮬레이터에서 보여줘','현재 궤적 Isaac에서 보여줘',
    '로봇 움직이는 거 보여줘','Robot Preview 실행해줘','시뮬레이션 돌려줘']
AMBIGUOUS = ['실제 경로 해줘','로봇 경로 만들어','최종으로 해줘']


@pytest.fixture
def fixture(tmp_path,monkeypatch,request):
    for module in ('native','native_rough3d','guided_vla','config'):
        monkeypatch.setattr('backend.model_clients.'+module+'.ROOT',tmp_path)
    def denied(*args,**kwargs): raise AssertionError('No network or real model in decision tests')
    async def async_denied(*args,**kwargs): denied()
    import openai
    monkeypatch.setattr(openai,'OpenAI',denied)
    monkeypatch.setattr(openai,'AsyncOpenAI',denied)
    monkeypatch.setattr(httpx.Client,'send',denied)
    monkeypatch.setattr(httpx.AsyncClient,'send',async_denied)
    if getattr(request,'param',None)=='baseline':
        from tests.module_fakes import module_workflow
        workflow,transport=module_workflow(tmp_path)
        calls={'segment':[],'rough3d':workflow.rough3d.received_masks}
    else:workflow,transport,calls=candidate_workflow(tmp_path)
    return workflow,transport,calls


def stream(api,job,message,sid=None):
    sid=sid or api.post('/api/agent/sessions').json()['session_id']
    return events(api.post('/api/agent/chat/stream',json={'session_id':sid,'job_id':str(job.id),'message':message}))


def app_for(workflow,runner=None):
    return create_app(workflow=workflow,simulator=FakeSimulator(),agent_runner=runner or FakeRunner(),
                      agent_settings=AgentSettings(api_key='offline-private-key'))


def summaries(log):return [data for event,data in log if event=='decision_summary']


@pytest.mark.parametrize('message',POSITIVE)
def test_clear_execution_routes_shared_gate_once(fixture,message):
    workflow,transport,calls=fixture
    job=rough_job(workflow);mask=job.mask.model_dump();before={k:len(v) for k,v in calls.items()}
    runner=FakeRunner();app=app_for(workflow,runner)
    with TestClient(app) as api: log=stream(api,job,message)
    assert log[-1][1]['ok'] is True,log
    assert [d['tool'] for e,d in log if e=='tool_started']==['get_workspace_state','run_final_trajectory_prediction']
    assert all(s['final_predictor']=='guided_vla' for s in summaries(log))
    assert len(transport.calls)==1 and transport.health_calls==1
    assert runner.calls==0 and not app.state.simulator.calls
    assert before=={k:len(v) for k,v in calls.items()}
    assert workflow.get_job(job.id).mask.model_dump()==mask
    result=summaries(log)
    assert result[0]['status']=='planned' and result[-1]['status']=='completed'
    assert any(s['status']=='running' and s['current_step']=='guided_vla' for s in result)
    assert result[-1]['intent']=='guided_vla_execution' and result[-1]['point_count']==9
    assert result[-1]['next_step']=='simulator_panel'


@pytest.mark.parametrize('message',NEGATIVE)
def test_explanation_does_not_allow_paid_tool(fixture,message):
    workflow,transport,_=fixture
    job=rough_job(workflow)
    ctx=WeldingAgentContext(job.id,'test',message,workflow,FakeSimulator(),lambda *_:None)
    ctx.remember(job)
    result=asyncio.run(invoke(ctx,'run_guided_vla'))
    assert result['code']=='guided_vla_intent_required'
    assert not transport.calls and transport.health_calls==0
    # Literal non-execution VLA requests bypass LLM tool-choice as well.
    if parse_request(message).handled:
        runner=FakeRunner()
        with TestClient(app_for(workflow,runner)) as api:log=stream(api,job,message)
        assert log[-1][1]['ok'] and runner.calls==0
        assert summaries(log)[-1]['reason_code']=='READ_ONLY_REQUEST'


@pytest.mark.parametrize('message',SIMULATOR)
@pytest.mark.parametrize('ready',[False,True])
def test_preview_does_not_implicitly_generate_vla(fixture,message,ready):
    workflow,transport,calls=fixture
    job=rough_job(workflow)
    if ready:job=workflow.run_guided_vla(job.id)
    before=(len(transport.calls),transport.health_calls,{k:len(v) for k,v in calls.items()})
    app=app_for(workflow)
    with TestClient(app) as api:log=stream(api,job,message)
    assert before==(len(transport.calls),transport.health_calls,{k:len(v) for k,v in calls.items()})
    assert not app.state.simulator.calls and app.state.agent.runner.calls==0
    assert summaries(log)[-1]['status']==('completed' if ready else 'blocked')
    assert summaries(log)[-1]['reason_code']=='SIMULATOR_PREVIEW_INTENT'


@pytest.mark.parametrize('message',AMBIGUOUS)
def test_ambiguous_asks_without_calls(fixture,message):
    workflow,transport,_=fixture;job=rough_job(workflow)
    with TestClient(app_for(workflow)) as api:log=stream(api,job,message)
    assert summaries(log)[-1]['status']=='clarification'
    assert not transport.calls and transport.health_calls==0
    assert '최종 3D 궤적' in ''.join(d['text'] for e,d in log if e=='assistant_delta')


def test_explicit_multi_action_runs_vla_only(fixture):
    workflow,transport,_=fixture;job=rough_job(workflow);app=app_for(workflow)
    with TestClient(app) as api:log=stream(api,job,'VLA 생성 후 시뮬레이터까지 보여줘')
    assert log[-1][1]['ok'] and len(transport.calls)==1 and not app.state.simulator.calls
    assert summaries(log)[-1]['next_step']=='simulator_panel'


@pytest.mark.parametrize('case,code',[
    ('unapproved','GUIDED_VLA_MASK_APPROVAL_REQUIRED'),('rough_missing','GUIDED_VLA_GUIDANCE_REQUIRED'),
    ('instruction_changed','GUIDED_VLA_INPUT_CHANGED'),('approval_changed','GUIDED_VLA_INPUT_CHANGED'),
    ('sample_changed','GUIDED_VLA_INPUT_CHANGED'),('native_output_changed','GUIDED_VLA_INPUT_CHANGED'),
    ('multi_region','GUIDED_VLA_SINGLE_REGION_REQUIRED'),('backend_missing','GUIDED_VLA_BACKEND_NOT_CONFIGURED')])
@pytest.mark.parametrize('fixture',['baseline'],indirect=True)
def test_prerequisites_block_before_health_or_prediction(fixture,case,code):
    workflow,transport,calls=fixture;job=rough_job(workflow)
    if case=='unapproved':job=workflow.set_mask(job.id)
    elif case=='rough_missing':job.rough3d=None
    elif case=='instruction_changed':job.instruction.text='오른쪽에서 왼쪽으로 용접해'
    elif case=='approval_changed':job.mask.approved_at=job.mask.approved_at.replace(year=2025)
    elif case=='sample_changed':job.scene.sample_id='OTHER_2'
    elif case=='native_output_changed':
        record=read_json(workflow.storage.artifact_path('native_context',job.rough3d.artifact_id,'.rough3d.json'))
        from pathlib import Path
        (Path(record['directory'])/'query_image_guidance_2d.json').write_text('{}')
    elif case=='multi_region':job.mask.regions.append(job.mask.regions[0].model_copy(update={'region_id':99}))
    elif case=='backend_missing':workflow.guided_vla.transport=None
    workflow.storage.save_job(job)
    before={k:len(v) for k,v in calls.items()}
    with TestClient(app_for(workflow)) as api:
        sid=api.post('/api/agent/sessions').json()['session_id']
        response=api.post('/api/agent/chat/stream',json={'session_id':sid,'job_id':str(job.id),'message':'VLA로 실제 궤적 생성해줘'})
    if case in ('instruction_changed','approval_changed','sample_changed','native_output_changed'):
        # Existing authoritative snapshot admission rejects corruption even
        # before SSE/context creation. Do not bypass this stronger native gate.
        assert response.status_code==422 and response.json()['code']=='NATIVE_OUTPUT_HARD_INVALID'
    else:
        log=events(response)
        assert [d['code'] for e,d in log if e=='error']==[code],log
        assert summaries(log)[-1]['status']=='blocked'
    assert not transport.calls and transport.health_calls==0
    assert before=={k:len(v) for k,v in calls.items()}
    assert not workflow.guided_vla.settings.attempts.exists()


def test_current_ready_reuse_and_rerun_policy_no_duplicates(fixture):
    workflow,transport,_=fixture;job=rough_job(workflow);app=app_for(workflow)
    with TestClient(app) as api:
        first=stream(api,job,'VLA 실행해줘')
        ready=workflow.get_job(job.id)
        second=stream(api,ready,'실제 3D 궤적 생성해줘')
        assert summaries(second)[-1]['reason_code']=='GUIDED_VLA_ALREADY_READY'
        third=stream(api,ready,'VLA 다시 실행해줘')
        assert any(e=='error' and d['code']=='GUIDED_VLA_RERUN_NOT_SUPPORTED' for e,d in third)
        assert first[-1][1]['ok'] and second[-1][1]['ok'] and not third[-1][1]['ok']
    assert len(transport.calls)==1 and transport.health_calls==1


def test_reuse_rejects_changed_package(fixture):
    workflow,transport,_=fixture;job=workflow.run_guided_vla(rough_job(workflow).id)
    attempt=workflow.guided_vla.settings.attempts/str(job.vla_prediction.attempt_id)
    (attempt/'trajectory.npz').write_bytes(b'changed')
    with TestClient(app_for(workflow)) as api:log=stream(api,job,'VLA 실행해줘')
    assert any(e=='error' and d['code']=='GUIDED_VLA_INPUT_CHANGED' for e,d in log)
    assert len(transport.calls)==1 and transport.health_calls==1


def test_existing_result_reusable_without_current_token_or_health(fixture):
    workflow,transport,_=fixture;job=workflow.run_guided_vla(rough_job(workflow).id)
    workflow.guided_vla.transport=None
    with TestClient(app_for(workflow)) as api:log=stream(api,job,'VLA 실행해줘')
    assert log[-1][1]['ok'] and summaries(log)[-1]['reason_code']=='GUIDED_VLA_ALREADY_READY'
    assert len(transport.calls)==1 and transport.health_calls==1


def test_job_admission_and_revision_remain_authoritative(fixture):
    workflow,transport,_=fixture;job=rough_job(workflow);app=app_for(workflow)
    service=app.state.agent
    with service.manual_mutation(job.id):
        with TestClient(app) as api:
            sid=api.post('/api/agent/sessions').json()['session_id']
            result=api.post('/api/agent/chat/stream',json={'session_id':sid,'job_id':str(job.id),'message':'VLA 실행해줘'})
            assert result.status_code==409 and result.json()['code']=='run_in_progress'
    ctx=WeldingAgentContext(job.id,'test','VLA 실행해줘',workflow,FakeSimulator(),lambda *_:None)
    ctx.remember(job)
    # An actual Workflow instruction mutation invalidates downstream/revision.
    workflow.parse_instruction(job.id,'오른쪽에서 왼쪽으로 용접해')
    assert asyncio.run(invoke(ctx,'run_guided_vla'))['code']=='workspace_changed'
    assert not transport.calls and transport.health_calls==0


def test_safe_summary_rejects_text_arguments_arrays_and_unknown_codes(fixture):
    workflow,transport,_=fixture;job=rough_job(workflow)
    with TestClient(app_for(workflow)) as api:log=stream(api,job,'VLA 실행해줘')
    safe=summaries(log)[-1]
    for field,value in [('raw_prompt','secret'),('tool_kwargs',{'path':'C:/private'}),('points_xyz',[[1,2,3]]),
                        ('reason_code','hidden internal reasoning'),('current_step','sk-private-token')]:
        with pytest.raises(ValidationError):AgentDecisionSummary.model_validate({**safe,field:value})
    text=json.dumps(log,ensure_ascii=False)
    assert all(s not in text for s in ['points_pixel','points_xyz','cot_ko.md','vla_prompt.md',
        'query_image_guidance_2d','offline-private-key',str(workflow.storage.root),'raw_instruction_ko','request_manifest'])
    # The event boundary rejects a runner attempting to inject extra/raw fields.
    class UnsafeRunner:
        async def run(self,ctx,*_):
            ctx.emit('decision_summary',{**safe,'raw_prompt':'hidden scratchpad sk-private-token'})
            return '안전한 답변'
    with TestClient(app_for(workflow,UnsafeRunner())) as api:log=stream(api,job,'안녕하세요')
    assert 'hidden scratchpad' not in json.dumps(log)
    assert all(term not in json.dumps(log) for term in ('chain-of-thought','raw reasoning','hidden reasoning','system prompt','API secret','raw tool args'))


def test_summary_mask_redetection_and_rough_lifecycle(fixture):
    workflow,transport,calls=fixture;job=workflow.load_sample('SAMPLE_1')
    with TestClient(app_for(workflow)) as api:
        detected=stream(api,job,'마스크 다시 만들어줘. 조금 더 전체 영역으로 해줘')
        assert summaries(detected)[-1]['intent']=='mask_redetection'
        assert summaries(detected)[-1]['next_step']=='approve_f_mask'
        job=workflow.get_job(job.id);job=workflow.approve_mask(job.id,job.mask.id,'F')
        planned=stream(api,job,'왼쪽에서 오른쪽으로 경로 만들어줘')
        assert summaries(planned)[-1]['intent']=='rough_trajectory_generation'
        assert summaries(planned)[-1]['next_step']=='run_vla'
    assert len(calls['segment'])==1 and len(calls['rough3d'])==1 and not transport.calls


def test_server_error_summary_without_retry(fixture):
    workflow,transport,_=fixture;job=rough_job(workflow)
    transport.health=lambda:{'status':'loading'}
    with TestClient(app_for(workflow)) as api:log=stream(api,job,'VLA 실행해줘')
    assert any(e=='error' and d['code']=='GUIDED_VLA_SERVER_UNAVAILABLE' for e,d in log)
    assert summaries(log)[-1]['status']=='blocked' and not transport.calls


def test_summary_failure_cannot_break_semantic_tools_or_admission(fixture):
    workflow,transport,_=fixture;job=rough_job(workflow)
    def emit(event,data):
        if event=='decision_summary':raise RuntimeError('private exception must not enter logs')
    ctx=WeldingAgentContext(job.id,'test','작업 상태 확인',workflow,FakeSimulator(),emit)
    assert asyncio.run(invoke(ctx,'get_workspace_state'))['mask_ready']
    assert ctx.checked and not ctx.failures and not transport.calls


def test_native_question_summary_and_vla_request_never_consumes_reply(tmp_path,monkeypatch):
    from tests.test_trajectory_clarification import clarification_output
    for module in ('native','native_rough3d','guided_vla','config'):
        monkeypatch.setattr('backend.model_clients.'+module+'.ROOT',tmp_path)
    workflow,transport,calls=candidate_workflow(tmp_path,rough_output_transform=clarification_output,vertical=True)
    job=workflow.load_sample('SAMPLE_1');job=workflow.set_mask(job.id)
    job=workflow.approve_mask(job.id,job.mask.id,'F')
    with TestClient(app_for(workflow)) as api:
        first=stream(api,job,'왼쪽에서 오른쪽으로 경로 만들어줘')
        pending=workflow.get_job(job.id)
        assert summaries(first)[-1]['status']=='clarification'
        assert summaries(first)[-1]['next_step']=='answer_question'
        second=stream(api,pending,'실제 3D 궤적 생성해줘')
        assert any(e=='error' and d['code']=='GUIDED_VLA_CLARIFICATION_REQUIRED' for e,d in second)
        assert workflow.get_job(job.id).trajectory_clarification.id==pending.trajectory_clarification.id
    assert len(calls['segment'])==1 and len(calls['rough3d'])==1
    assert not transport.calls and transport.health_calls==0
    assert not any(s in json.dumps(first+second) for s in ('HIDDEN_PRIVATE_ANALYSIS','PRIVATE_COT','FULL_PRIVATE_PROMPT'))
