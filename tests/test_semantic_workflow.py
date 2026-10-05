"""Fake SDK + real Workflow / native adapters. All inference transports are offline."""
import asyncio
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.agent.config import AgentSettings
from backend.agent.context import WeldingAgentContext
from backend.agent.welding_agent import SDKRunner
from backend.main import create_app
from backend.model_clients.contracts import ModelFault, Provenance
from backend.model_clients.native import read_json, sha256
from tests.agent_fakes import FakeSimulator, invoke
from tests.native_stack_fakes import candidate_workflow
from tests.semantic_fakes import two_region_segment, matching_multi_rough, ScriptedSemanticModel
from tests.test_agent import events


@pytest.fixture
def native(tmp_path, monkeypatch):
    for module in ('native', 'native_rough3d', 'guided_vla', 'config'):
        monkeypatch.setattr('backend.model_clients.' + module + '.ROOT', tmp_path)
    import openai
    def forbidden(*args, **kwargs):
        raise AssertionError('No live API')
    monkeypatch.setattr(openai, 'OpenAI', forbidden)
    monkeypatch.setattr(openai, 'AsyncOpenAI', forbidden)
    workflow, transport, calls = candidate_workflow(tmp_path,
        segment_output_transform=two_region_segment, rough_output_transform=matching_multi_rough)
    job = workflow.set_mask(workflow.load_sample('SAMPLE_1').id)
    return workflow, transport, calls, job


def turn(workflow, job, message, action, tool, arguments=None, *, instruction=None):
    steps = [('get_workspace_state', {}), ('choose_welding_action', {'action': action})]
    if instruction:
        steps.append(('set_weld_instruction', instruction))
    if tool:
        steps.append((tool, arguments or {}))
    app = create_app(workflow=workflow, simulator=FakeSimulator(),
        agent_runner=SDKRunner(model_override=ScriptedSemanticModel(steps)),
        agent_settings=AgentSettings(api_key='offline', max_turns=8))
    with TestClient(app) as client:
        sid = client.post('/api/agent/sessions').json()['session_id']
        return events(client.post('/api/agent/chat/stream', json={
            'session_id': sid, 'job_id': str(job.id), 'message': message}))


@pytest.mark.parametrize('message,operation,relation', [
    ('왼쪽은 이미 용접했어. 왼쪽 부분은 제거해줘', 'REMOVE', 'LEFT'),
    ('오른쪽만 남겨줘', 'KEEP_ONLY', 'RIGHT'),
    ('첫 번째 영역은 제외해', 'REMOVE', 'FIRST'),
])
def test_sdk_edit_draft_whole_component_and_invalidate(native, message, operation, relation):
    w, transport, calls, job = native
    job = w.approve_mask(job.id, job.mask.id)
    w.parse_instruction(job.id, '왼쪽에서 오른쪽으로 용접해')
    job = w.plan(job.id)
    assert len(job.rough_trajectory.segments) == 2
    before = np.asarray(w.storage.read_image('masks', job.mask.id)).copy()
    old_path = w.storage.artifact_path('masks', job.mask.id)
    old_hash = sha256(old_path)
    original_id = job.mask.id
    trace = turn(w, job, message, 'MASK_EDIT', 'edit_weld_mask',
        dict(operation=operation, target_relation=relation, reason='ALREADY_WELDED', view='F'))
    assert trace[-1][1]['ok'], trace
    current = w.get_job(job.id)
    after = np.asarray(w.storage.read_image('masks', current.mask.id))
    assert not after[:, :50].any()
    assert np.array_equal(after[:, 50:], before[:, 50:])
    assert sha256(old_path) == old_hash
    assert current.mask.id != original_id and current.mask.edited_from_mask_id == original_id
    assert current.mask.mask_source == 'manual_edited'
    assert current.mask.approved is False and current.mask.approved_at is None
    assert current.mask.artifact.provenance.native_source_artifact_id == job.mask.artifact.provenance.native_source_artifact_id
    assert current.instruction is current.rough_trajectory is current.rough3d is current.vla_prediction is current.native_output is None
    assert len(calls['segment']) == len(calls['rough3d']) == 1 and not transport.calls
    decision = [d for e, d in trace if e == 'decision_summary'][-1]
    assert decision['intent'] == 'mask_edit' and decision['selected_action'] == 'mask_edit'
    assert decision['region_count'] == 1 and decision['segment_count'] == 0


def test_single_component_clarifies_without_arbitrary_crop(native):
    w, _, calls, job = native
    job = w.edit_mask(job.id, operation='REMOVE', relation='LEFT')
    before_id, before_hash = job.mask.id, sha256(w.storage.artifact_path('masks', job.mask.id))
    trace = turn(w, job, '왼쪽 부분 조금 지워줘', 'MASK_EDIT', 'edit_weld_mask',
        dict(operation='REMOVE', target_relation='LEFT', reason='EXCLUDED_BY_USER', view='F'))
    assert trace[-1][1]['ok'], trace
    current = w.get_job(job.id)
    assert current.mask.id == before_id and sha256(w.storage.artifact_path('masks', before_id)) == before_hash
    assert [d for e, d in trace if e == 'decision_summary'][-1]['status'] == 'clarification'
    assert len(calls['segment']) == 1 and not calls['rough3d']


@pytest.mark.parametrize('message', ['마스크 다시 그려줘', '내가 수정한 마스크 기준으로 다시 보정해줘'])
def test_refinement_fail_closed_no_redetection(native, message):
    w, transport, calls, job = native
    job = w.edit_mask(job.id, operation='REMOVE', relation='LEFT')
    class Unavailable:
        def segment(self,*args,**kwargs):raise AssertionError('No redetection')
    w.segmentation=Unavailable()
    trace = turn(w, job, message, 'MASK_REFINE', 'refine_weld_mask')
    assert not trace[-1][1]['ok']
    assert any(e == 'error' and d['code'] == 'MASK_REFINEMENT_MODEL_SUPPORT_PARTIAL' for e, d in trace)
    assert w.get_job(job.id).mask.id == job.mask.id
    assert len(calls['segment']) == 1 and not calls['rough3d'] and not transport.calls
    assert [d for e, d in trace if e == 'decision_summary'][-1]['intent'] == 'mask_refinement'


def test_conditioned_refinement_boundary_provenance_and_constraint_guard(native):
    w, _, calls, job = native
    original = w.storage.read_image('masks', job.mask.id)
    job = w.edit_mask(job.id, operation='REMOVE', relation='LEFT')
    current = w.storage.read_image('masks', job.mask.id)
    class ConditionedFake:
        resurrect = False
        received = []
        def refine(self, image, binary, metadata, *, instruction):
            self.received.append((image.size, binary.tobytes(), metadata.id, instruction))
            out = original.copy() if self.resurrect else binary.copy()
            out.info['model_provenance'] = Provenance(model_name='offline-conditioned', model_version='1',
                latency_ms=0, reference_mode='native')
            return out
        def segment(self, *args, **kwargs):
            raise AssertionError('No redetection fallback')
    fake = ConditionedFake()
    w.segmentation = fake
    refined = w.refine_mask(job.id, instruction='현재 마스크 보정')
    assert fake.received[0][1] == current.tobytes() and fake.received[0][2] == job.mask.id
    assert refined.mask.mask_source == 'ai_refined' and refined.mask.edited_from_mask_id == job.mask.id
    assert not refined.mask.approved and refined.mask.approved_at is None
    assert refined.mask.artifact.provenance.source_mask_id == job.mask.id
    fake.resurrect = True
    with pytest.raises(ModelFault) as error:
        w.refine_mask(job.id, instruction='보정')
    assert error.value.code == 'MASK_REFINEMENT_CONSTRAINT_VIOLATION'
    assert w.get_job(job.id).mask.id == refined.mask.id
    assert len(calls['segment']) == 1 and not calls['rough3d']


def test_redetection_is_distinct_unapproved_native_call(native):
    w, _, calls, job = native
    job = w.edit_mask(job.id, operation='REMOVE', relation='LEFT')
    trace = turn(w, job, '마스크 다시 찾아줘', 'MASK_REDETECT', 'redetect_weld_mask')
    assert trace[-1][1]['ok'], trace
    assert len(calls['segment']) == 2 and not calls['rough3d']
    fresh = w.get_job(job.id)
    assert len(fresh.mask.regions) == 2 and not fresh.mask.approved
    assert fresh.mask.mask_source == 'vlm_segment'
    assert fresh.mask.artifact.provenance.source_mask_id == job.mask.id


@pytest.mark.parametrize('backend', ['gpt', 'guided_vla'])
@pytest.mark.parametrize('order', [[0, 1], [1, 0]])
def test_sdk_rough_multi_region_correspondence_never_final(native, backend, order):
    w, transport, calls, job = native
    class FinalForbidden:
        def status(self):return {'backend': backend, 'configured': True}
        def run(self, *args, **kwargs):raise AssertionError('Rough must not call final')
    w.guided_vla = FinalForbidden()
    job = w.approve_mask(job.id, job.mask.id, 'F')
    trace = turn(w, job, '왼쪽부터 오른쪽 순서로 가궤적 예측해줘', 'ROUGH_TRAJECTORY_GENERATE', 'generate_rough_trajectory',
        instruction=dict(direction='left_to_right', start_region=order[0], region_order=order, skip_regions=[]))
    assert trace[-1][1]['ok'], trace
    current = w.get_job(job.id)
    assert current.state.value == 'ROUGH_PATH_READY'
    assert [s.region_id for s in current.rough_trajectory.segments] == order
    assert len(current.rough_trajectory.segments) == 2
    assert all(s.mode == 'weld' for s in current.rough_trajectory.segments)
    assert all(not s.connected_to_next for s in current.native_output.candidate.segments)
    for segment in current.rough_trajectory.segments:
        x = [p.x for p in segment.points]
        assert all(v < 50 for v in x) if segment.region_id == 0 else all(v > 50 for v in x)
    assert len(calls['rough3d']) == 1 and not transport.calls
    input_session = Path(calls['rough3d'][0][-1])
    proof = read_json(input_session.parent / f'{input_session.name}.json')
    assert proof['region_order'] == order
    assert sha256(input_session / 'yolo/detections.json') == proof['yolo_source_sha256']
    names = [d['tool'] for e, d in trace if e == 'tool_started']
    assert 'generate_rough_trajectory' in names and 'run_final_trajectory_prediction' not in names
    decision = [d for e, d in trace if e == 'decision_summary'][-1]
    assert decision['selected_action'] == 'trajectory3' and decision['segment_count'] == decision['region_count'] == 2


@pytest.mark.parametrize('action,tool', [('STATUS_OR_EXPLANATION', None), ('MASK_APPROVE', 'request_mask_approval')])
def test_readonly_or_approval_notice_no_inference(native, action, tool):
    w, transport, calls, job = native
    trace = turn(w, job, '현재 상태를 알려줘', action, tool)
    assert trace[-1][1]['ok'], trace
    assert not w.get_job(job.id).mask.approved
    assert len(calls['segment']) == 1 and not calls['rough3d'] and not transport.calls


def test_approval_gate_after_semantic_selection_and_wrong_tool_denied(native):
    w, transport, calls, job = native
    trace = turn(w, job, '가궤적 예측해줘', 'ROUGH_TRAJECTORY_GENERATE', 'generate_rough_trajectory',
        instruction=dict(direction='left_to_right', start_region=None, region_order=None, skip_regions=[]))
    assert not trace[-1][1]['ok']
    assert any(e == 'error' and d['code'] == 'MASK_APPROVAL_REQUIRED' for e, d in trace)
    assert not calls['rough3d'] and not transport.calls
    ctx = WeldingAgentContext(job.id, uuid4(), '가궤적 예측해줘', w, FakeSimulator(), lambda *args: None)
    async def run():
        await invoke(ctx, 'get_workspace_state')
        await invoke(ctx, 'choose_welding_action', action='ROUGH_TRAJECTORY_GENERATE')
        result = await invoke(ctx, 'run_final_trajectory_prediction')
        assert result['code'] == 'SEMANTIC_ACTION_MISMATCH'
        result = await invoke(ctx, 'choose_welding_action', action='FINAL_TRAJECTORY_GENERATE')
        assert result['code'] == 'SEMANTIC_ACTION_MISMATCH'
    asyncio.run(run())
    assert not calls['rough3d'] and not transport.calls


def test_current_workspace_revision_required_and_final_multiregion_clarifies(native):
    w, transport, calls, job = native
    ctx = WeldingAgentContext(job.id, uuid4(), '왼쪽 제거해줘', w, FakeSimulator(), lambda *args: None)
    async def stale():
        await invoke(ctx, 'get_workspace_state')
        w.approve_mask(job.id, job.mask.id)
        result = await invoke(ctx, 'choose_welding_action', action='MASK_EDIT')
        assert result['code'] == 'workspace_changed'
    asyncio.run(stale())
    job = w.get_job(job.id)
    w.parse_instruction(job.id,'왼쪽에서 오른쪽으로 용접해')
    job=w.plan(job.id)
    trace = turn(w, job, '최종 3D 궤적 생성해줘', 'FINAL_TRAJECTORY_GENERATE', 'run_final_trajectory_prediction')
    assert trace[-1][1]['ok'], trace
    assert [d for e, d in trace if e == 'decision_summary'][-1]['status'] == 'clarification'
    assert not transport.calls and len(calls['rough3d'])==1


def test_api_manual_sync_draft_does_not_fabricate_human_approval(native):
    w, _, _, job = native
    png = BytesIO();w.storage.read_image('masks', job.mask.id).save(png, format='PNG')
    with TestClient(create_app(workflow=w, simulator=FakeSimulator(), agent_settings=AgentSettings(api_key='offline'))) as client:
        response = client.post('/api/masks/manual', data={'job_id':str(job.id), 'view_id':'F',
            'edited_from_mask_id':str(job.mask.id), 'require_review':'true'}, files={'file':('mask.png',png.getvalue(),'image/png')})
    assert response.status_code == 200, response.text
    assert response.json()['mask']['approved'] is False and response.json()['mask']['approved_at'] is None


@pytest.mark.parametrize('remove_component,skip', [(True, []), (False, [0])])
def test_single_or_skipped_region_rough_still_only_calls_trajectory3(native, remove_component, skip):
    w, transport, calls, job = native
    if remove_component:
        job=w.edit_mask(job.id,operation='REMOVE',relation='LEFT')
    job=w.approve_mask(job.id,job.mask.id)
    expected=[r.region_id for r in job.mask.regions if r.region_id not in skip]
    trace=turn(w,job,'가궤적 예측해줘','ROUGH_TRAJECTORY_GENERATE','generate_rough_trajectory',
        instruction=dict(direction='left_to_right',start_region=None,region_order=None,skip_regions=skip))
    assert trace[-1][1]['ok'],trace
    current=w.get_job(job.id)
    assert current.state.value=='ROUGH_PATH_READY'
    assert [s.region_id for s in current.rough_trajectory.segments]==expected
    assert len(calls['rough3d'])==1 and not transport.calls


def test_status_selection_cannot_infer_and_sdk_tools_have_no_coordinate_arguments(native):
    w,transport,calls,job=native
    ctx=WeldingAgentContext(job.id,uuid4(),'가궤적 모델이 뭐야?',w,FakeSimulator(),lambda *_:None)
    async def run():
        await invoke(ctx,'get_workspace_state')
        await invoke(ctx,'choose_welding_action',action='STATUS_OR_EXPLANATION')
        result=await invoke(ctx,'generate_rough_trajectory')
        assert result['code']=='SEMANTIC_ACTION_MISMATCH'
        result=await invoke(ctx,'redetect_weld_mask')
        assert result['code']=='SEMANTIC_ACTION_MISMATCH'
    asyncio.run(run())
    from backend.agent.semantic_tools import SEMANTIC_TOOLS
    for tool in SEMANTIC_TOOLS:
        assert not {'x','y','z','points','pixels','polygon','command','path'} & set(tool.params_json_schema['properties'])
        assert tool.params_json_schema['additionalProperties'] is False
    assert len(calls['segment'])==1 and not calls['rough3d'] and not transport.calls


def test_completed_semantic_clarification_reply_does_not_keep_waiting(native):
    from backend.agent.semantic import request_for
    from backend.agent.decision import summarize
    w,_,_,job=native
    job=w.approve_mask(job.id,job.mask.id)
    w.parse_instruction(job.id,'왼쪽에서 오른쪽으로 용접해')
    job=w.plan(job.id)
    summary=summarize(request_for('ANSWER_CLARIFICATION'),job,status='completed')
    assert summary.status=='completed' and summary.next_step=='run_vla'
