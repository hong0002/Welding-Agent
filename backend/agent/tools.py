"""Only semantic operations are exposed to the model; never paths, commands or points."""
import asyncio
import json
import time
from typing import Literal

from agents import RunContextWrapper, function_tool

from backend.agent.config import AgentFault
from backend.agent.context import WeldingAgentContext, rough_summary, simulator_summary, workspace_summary
from backend.orchestrator.region_selection import resolve_regions
from backend.schemas import RegionId, StructuredInstruction
from backend.agent.scene_intent import scene_sample
from backend.model_clients.contracts import ModelFault


def invalid_arguments(ctx, _error):
    fault = AgentFault("tool_validation_error", "Agent 도구 입력 형식이 올바르지 않습니다.")
    ctx.context.failures.append(fault)
    ctx.context.emit("error", {"code": fault.code, "message": fault.message})
    return json.dumps({"ok": False, "code": fault.code, "message": fault.message}, ensure_ascii=False)


async def load_scene_request(context, sample_id):
    def load():
        if scene_sample(context.message) != sample_id:
            raise AgentFault('scene_load_intent_required','현재 메시지에 sample ID와 명시적인 불러오기 요청이 필요합니다.',403)
        if 'scene_load' in context.completed:
            raise AgentFault('scene_already_loaded','이번 요청에서 Scene을 이미 불러왔습니다.',409)
        context.completed['scene_load']=True
        job=context.workflow.load_sample(sample_id)
        context.adopt_job(job)
        return {'job_id':str(job.id),'sample_id':job.scene.sample_id,'split':job.scene.split,
                'views':list(job.scene.views),'approval_required':True}
    return await context.call('load_welding_scene',lambda:context.work(load))


@function_tool(failure_error_function=invalid_arguments)
async def load_welding_scene(ctx:RunContextWrapper[WeldingAgentContext],sample_id:str)->dict:
    """Load the dataset's nine views only on explicit latest sample-load intent.
    Accept sample ID only; no paths or images. Does not run Segment/Rough/VLA.
    """
    return await load_scene_request(ctx.context,sample_id)


@function_tool(failure_error_function=invalid_arguments)
async def get_workspace_state(ctx: RunContextWrapper[WeldingAgentContext]) -> dict:
    """Read the CURRENT workspace: confirmed mask region IDs, bounds, centroids, selection and state.
    Always call this before modifying instructions or planning in each turn. No image or path arrays.
    """
    async def operation():
        job = await ctx.context.work(ctx.context.job) if ctx.context.job_id else None
        if job:
            ctx.context.remember(job)
        return workspace_summary(job)
    return await ctx.context.call("get_workspace_state", operation)


@function_tool(failure_error_function=invalid_arguments)
async def set_weld_instruction(
    ctx: RunContextWrapper[WeldingAgentContext], direction: Literal["left_to_right", "right_to_left", "top_to_bottom", "bottom_to_top"],
    start_region: RegionId | None, region_order: list[RegionId] | None, skip_regions: list[RegionId],
) -> dict:
    """Apply semantic instruction against current confirmed region IDs, invalidating older previews.
    start_region is an actual ID or null. region_order is all active IDs in desired order, or null
    for directional ordering. skip_regions is the complete excluded ID list, possibly empty.
    Preserve existing aspects not changed by the user's request. Never invent region IDs.
    """
    context = ctx.context
    def apply():
        with context.storage.lock:
            context.authorize_workspace_mutation()
            job = context.job(require_checked=True)
            if job.mask is None:
                raise AgentFault("mask_missing", "먼저 브러시로 용접 영역을 지정하고 마스크를 확정해주세요.", 409)
            structured = StructuredInstruction(direction=direction, start_region=start_region,
                                               region_order=region_order or [], skip_regions=skip_regions)
            structured = resolve_regions(structured, job.mask.regions)
            if not job.instruction or job.instruction.structured != structured:
                job = context.workflow.apply_instruction(job.id, context.message, structured)
                context.updated(job)
            return workspace_summary(job)
    return await context.call("set_weld_instruction", lambda: context.work(apply))


async def _plan(ctx, tool_name):
    context = ctx.context
    def plan():
        with context.storage.lock:
            context.authorize_workspace_mutation()
            job = context.job(require_checked=True)
            labels = {"rough": "Rough trajectory 생성", "refine": "Dummy VLA preview", "validate": "Preview validation"}
            active_stage = None
            def progress(stage, completed, current):
                nonlocal active_stage
                active_stage = None if completed else stage
                label = labels[stage] + (" 통과" if stage == "validate" and completed else " 완료" if completed else " 실행 중")
                data = {"tool": stage, "label": label, "call_id": f"{context.sequence}-{stage}"}
                if completed: data["success"] = True
                context.emit("tool_completed" if completed else "tool_started", data)
                context.decision('running', stage)
            try:
                job = context.workflow.plan(job.id, progress=progress)
            except Exception as exc:
                if active_stage:
                    context.emit("tool_completed", {"tool": active_stage, "label": labels[active_stage] + " 실패",
                                 "call_id": f"{context.sequence}-{active_stage}", "success": False})
                job=context.workflow.get_job(job.id)
                context.updated(job)
                if (not isinstance(exc,ModelFault) or not job.native_output or not job.native_output.model_output
                        or not job.native_output.model_output.available):raise
            context.updated(job)
            if job.native_output:
                from backend.model_clients.native_candidate import summary
                return {**summary(job.native_output),'state':job.state.value,
                    'clarification_required':job.trajectory_clarification is not None,
                    'clarification_question':job.trajectory_clarification.question if job.trajectory_clarification else None,
                    'guided_vla_requires_explicit_intent':True,'is_robot_executable':False}
            rough = sum(len(s.points) for s in job.rough_trajectory.segments)
            if job.final_trajectory is None:
                return {**rough_summary(job.rough_trajectory), "state": job.state.value,
                        "rough_points": rough, "final_points": 0, "vla_connected": job.rough_mode == 'native_3d',
                        "guided_vla_requires_explicit_intent": job.rough_mode == 'native_3d',
                        "coordinate_space": "image_pixel", "is_robot_executable": False,
                        "rough_generator": job.rough_trajectory.generator}
            final = sum(len(s.points) for s in job.final_trajectory.segments)
            return {"state": job.state.value, "regions": [s.region_id for s in job.final_trajectory.segments],
                    "rough_points": rough, "final_points": final, "validation_passed": job.validation.valid,
                    "coordinate_space": "image_pixel", "units": "px", "is_robot_executable": False,
                    "rough_generator": job.rough_trajectory.generator, "final_generator": job.final_trajectory.generator}
    return await context.call(tool_name, lambda: context.work(plan))


async def route_clarification_request(context):
    """Deterministic human-message route; deliberately not an LLM answer tool."""
    from backend.orchestrator.clarification import message
    job = await context.work(context.job)
    context.remember(job)
    pending = job.trajectory_clarification
    expected = context.expected_clarification_id
    if not pending or (expected is not None and pending.id != expected):
        raise AgentFault('CLARIFICATION_STALE','이 질문은 더 이상 현재 질문이 아닙니다. 현재 작업의 질문을 확인하세요.',409)
    async def answer():
        def operation():
            with context.storage.lock:
                current = context.job(require_checked=True)
                if 'clarification' in context.completed:
                    raise AgentFault('clarification_already_attempted','이번 답변은 이미 처리했습니다.',409)
                context.completed['clarification'] = True
                return context.workflow.answer_trajectory_clarification(current.id, pending.id, context.message)
        result = await context.work(operation)
        context.updated(result)
        return workspace_summary(result)
    await context.call('answer_trajectory_clarification', answer)
    if context.failures:
        raise context.failures[0]
    current = await context.work(context.job)
    if current.trajectory_clarification:
        if current.trajectory_clarification.id != pending.id:
            context.emit('warning', {'code':'TRAJECTORY3_NEEDS_CLARIFICATION_AGAIN', 'message':'Trajectory3가 추가 질문을 반환했습니다. 현재 새 질문에 답해주세요.'})
        return message(current.trajectory_clarification)
    if current.rough3d:
        return '현재 승인된 F 마스크로 Trajectory3 경로를 생성하고 검증했습니다. Guided VLA는 별도로 실행해주세요.'
    if current.native_output and current.native_output.native_output_generated:
        return 'Trajectory3는 경로를 생성했습니다. 검증 조건을 통과하지 못해 Guided VLA는 차단됩니다.'
    return '최종 경로가 준비되지 않았습니다. 현재 MODEL OUTPUT 상태를 확인해주세요.'


@function_tool(failure_error_function=invalid_arguments)
async def create_current_weld_plan(ctx: RunContextWrapper[WeldingAgentContext]) -> dict:
    """Use the confirmed mask and instruction. Native mode stops at Rough; Dummy mode also
    refines/validates a Dummy preview. Return summaries only; never start simulation.
    """
    return await _plan(ctx, "create_current_weld_plan")


@function_tool(failure_error_function=invalid_arguments)
async def create_weld_preview_plan(ctx: RunContextWrapper[WeldingAgentContext]) -> dict:
    """Compatibility alias for create_current_weld_plan. Produces only a 2D preview."""
    return await _plan(ctx, "create_weld_preview_plan")


@function_tool(failure_error_function=invalid_arguments)
async def auto_segment_weld_region(ctx: RunContextWrapper[WeldingAgentContext]) -> dict:
    """Detect a weld mask only on explicit automatic-detection intent THIS turn.
    Requires get_workspace_state first. Never replace a user-indicated manual mask or act
    when the user says they will redraw. Updates the workspace; returns region summaries only.
    """
    return await detect_mask_request(ctx.context, 'auto_segment_weld_region')


async def detect_mask_request(context, tool_name='detect_weld_mask'):
    """Shared Agent/router operation: configured SegmentClient, no implicit approval."""
    def segment():
        with context.storage.lock:
            context.authorize_segmentation()
            job = context.job(require_checked=True)
            if "segmentation" in context.completed:
                raise AgentFault("segmentation_already_attempted", "이번 요청에서 자동 검출을 이미 시도했습니다. 현재 결과를 확인하세요.")
            context.completed["segmentation"] = True
            if job.mask is not None and not context.mask_intent.redetect:
                reused = True
            else:
                reused = False
                try:job = context.workflow.set_mask(job.id, instruction=context.message)
                except ModelFault:
                    job=context.workflow.get_job(job.id)
                    if not job.raw_segment_output or not job.raw_segment_output.model_output or not job.raw_segment_output.model_output.available:raise
                    context.updated(job)
                    return dict(views=list(job.raw_segment_output.model_output.mask_urls),region_count={},approval_required=True,
                        mask_source='vlm_segment',reused_existing_mask=False,mask_ready=False,state=job.state.value,
                        output_generated=True,validation_status='FAIL',displayable=job.raw_segment_output.model_output.displayable)
                context.updated(job)
            masks = {v:s.mask for v,s in job.scene.views.items() if s.mask} if job.scene.views else {'web':job.mask}
            summary = dict(views=list(masks),region_count={v:len(m.regions) for v,m in masks.items()},
                approval_required=not job.mask.approved,mask_source=job.mask.mask_source,
                reused_existing_mask=reused,mask_ready=job.mask.approved,state=job.state.value)
            return {**workspace_summary(job),**summary} if tool_name=='auto_segment_weld_region' else summary
    return await context.call(tool_name, lambda: context.work(segment))


@function_tool(failure_error_function=invalid_arguments)
async def detect_weld_mask(ctx: RunContextWrapper[WeldingAgentContext]) -> dict:
    """Detect using the configured native Segment model on explicit mask intent.
    No coordinate arguments. Never approve. Existing masks require explicit re-detection.
    Returns only views/counts/approval summary; invalidates downstream on re-detection.
    """
    return await detect_mask_request(ctx.context)


async def route_mask_request(context):
    async def inspect():
        job = await context.work(context.job)
        context.remember(job)
        return workspace_summary(job)
    await context.call('get_workspace_state', inspect)
    result = await detect_mask_request(context)
    if context.failures:
        raise context.failures[0]
    views = '/'.join(result['views'])
    if result.get('output_generated') and result.get('validation_status')=='FAIL':
        return 'Segment2가 마스크 결과를 생성했습니다. 검증을 통과하지 않아 적용하지 않았습니다. 모델 출력 패널에서 결과를 검토하거나 Brush/Eraser로 수정해주세요.'
    if result['reused_existing_mask']:
        return '기존 마스크를 유지했습니다. 재검출하려면 “마스크 다시 찾아줘”라고 요청해주세요.'
    return f'용접 영역을 자동 검출했습니다. {views} 마스크가 생성됐습니다. F 마스크를 확인하거나 Brush/Eraser로 수정한 뒤 “마스크 확정 · F”을 눌러주세요.'


@function_tool(failure_error_function=invalid_arguments)
async def get_simulator_status(ctx: RunContextWrapper[WeldingAgentContext]) -> dict:
    """Read cached simulator runtime status, separate from the welding preview workflow."""
    async def operation():
        return simulator_summary(await ctx.context.work(ctx.context.simulator.status))
    return await ctx.context.call("get_simulator_status", operation)


@function_tool(failure_error_function=invalid_arguments)
async def start_simulator(ctx: RunContextWrapper[WeldingAgentContext]) -> dict:
    """Start the configured simulator ONLY on explicit current user intent; wait until READY.
    Does not send or execute the current preview. Must never be invoked just because planning finished.
    """
    context = ctx.context
    async def operation():
        context.authorize("start")
        status = await context.work(context.simulator.status)
        if status["state"] not in ("READY", "RUNNING_SAMPLE", "STARTING"):
            if context.completed.get("start"):
                raise AgentFault("simulator_start_failed", "이번 요청의 Simulator 시작이 실패했습니다.")
            context.completed["start"] = True
            status = await context.work(context.simulator.start)
        deadline = time.monotonic() + context.ready_timeout
        while status["state"] == "STARTING" and time.monotonic() < deadline:
            await asyncio.sleep(min(0.3, context.ready_timeout / 2))
            status = await context.work(context.simulator.status)
        if status["state"] not in ("READY", "RUNNING_SAMPLE"):
            raise AgentFault("simulator_not_ready", "Simulator READY를 확인하지 못했습니다. Simulator 탭에서 상태를 확인하세요.")
        return simulator_summary(status)
    return await context.call("start_simulator", operation)


@function_tool(failure_error_function=invalid_arguments)
async def run_existing_vla_sample(ctx: RunContextWrapper[WeldingAgentContext]) -> dict:
    """This replays the configured pre-existing VLA prediction. It does NOT execute or simulate
    the current web preview trajectory. Requires explicit existing-sample intent THIS user turn
    and simulator READY. An accepted request is not proof of completed playback.
    """
    context = ctx.context
    async def operation():
        context.authorize("run")
        if "sample" in context.completed:
            return context.completed["sample"]
        status = await context.work(context.simulator.status)
        if status["state"] != "READY" or not status.get("can_run_sample"):
            raise AgentFault("simulator_not_ready", "기존 샘플 재생에는 Simulator READY 상태가 필요합니다.", 409)
        # Mark attempted before dispatch: an ambiguous failure must not replay a sample twice.
        context.completed["sample"] = {"ok": False, "message": "이미 샘플 실행을 요청했습니다. 상태를 확인하세요."}
        result = simulator_summary(await context.work(context.simulator.run_sample))
        context.completed["sample"] = result
        return result
    return await context.call("run_existing_vla_sample", operation)


@function_tool(failure_error_function=invalid_arguments)
async def stop_simulator(ctx: RunContextWrapper[WeldingAgentContext]) -> dict:
    """Stop owned simulator processes only when the latest user explicitly asks to stop."""
    context = ctx.context
    async def operation():
        context.authorize("stop")
        if "stop" not in context.completed:
            context.completed["stop"] = simulator_summary(await context.work(context.simulator.stop))
        return context.completed["stop"]
    return await context.call("stop_simulator", operation)


@function_tool(failure_error_function=invalid_arguments)
async def run_guided_vla(ctx:RunContextWrapper[WeldingAgentContext])->dict:
    """Run the current approved F-only NativeRough3D guidance through Guided VLA.
    Requires get_workspace_state and explicit VLA execution intent this turn.
    Return only artifact/count/frame/accuracy summary. Never start Simulator.
    """
    return await final_prediction_request(ctx.context)


@function_tool(failure_error_function=invalid_arguments)
async def run_final_trajectory_prediction(ctx:RunContextWrapper[WeldingAgentContext])->dict:
    """Request the backend-selected native final XYZ predictor after workspace inspection.
    The Agent never produces points, chooses paths/config or launches Simulator.
    Only explicit final trajectory execution intent authorizes inference.
    """
    return await final_prediction_request(ctx.context, generic=True)


async def final_prediction_request(context, generic=False):
    """Shared deterministic/SDK admission. No upstream generation or retry."""
    name='run_final_trajectory_prediction' if generic else 'run_guided_vla'
    def operation():
        context.authorize_guided_vla()
        client=context.workflow.final_predictor
        backend=client.status().get('backend') if client else None
        if not generic and backend=='gpt':
            raise AgentFault('FINAL_TRAJECTORY_BACKEND_MISMATCH','현재 GPT backend입니다. 최종 궤적 도구를 사용해주세요.',409)
        if 'gpt' in context.message.lower() and backend!='gpt':
            raise AgentFault('FINAL_TRAJECTORY_BACKEND_MISMATCH','Backend에서 GPT 최종 예측을 선택해야 합니다.',409)
        with context.storage.lock:
            job=context.job(require_checked=True)
            if 'guided_vla' in context.completed:raise AgentFault('guided_vla_already_attempted','이번 요청에서 최종 궤적 예측을 이미 시도했습니다.',409)
            def blocked(code, message, reason='GUIDED_VLA_PREREQUISITE_MISSING'):
                context.decision('blocked', name, reason)
                raise AgentFault(code,message,409)
            if job.trajectory_clarification:
                blocked('GUIDED_VLA_CLARIFICATION_REQUIRED','먼저 표시된 진행 방향 질문에 답해주세요.')
            if not job.scene.primary_view or job.scene.primary_view!='F':
                blocked('GUIDED_VLA_SCENE_REQUIRED','먼저 dataset sample의 F view를 준비해주세요.')
            if not job.mask or not job.mask.approved or not job.mask.approved_at:
                blocked('GUIDED_VLA_MASK_APPROVAL_REQUIRED','F 마스크를 검토하고 승인해주세요.')
            if not job.rough3d or not job.instruction:
                blocked('GUIDED_VLA_GUIDANCE_REQUIRED','먼저 Trajectory3 2D guidance를 생성해주세요.')
            if len(job.mask.regions)!=1:
                blocked('GUIDED_VLA_SINGLE_REGION_REQUIRED','현재 최종 궤적 예측은 단일 용접 영역만 지원합니다.')
            client=context.workflow.final_predictor
            if not client:
                blocked('GUIDED_VLA_BACKEND_NOT_CONFIGURED','최종 궤적 predictor 설정이 필요합니다.')
            try:
                # Read-only validation does not create an attempt or probe /health.
                client.validate_inputs(context.storage,job)
                if job.vla_prediction and job.state.value=='VLA_READY':
                    client.verify_current(context.storage,job)
                    if context.request_intent.rerun:
                        blocked('GUIDED_VLA_RERUN_NOT_SUPPORTED','현재 조건의 최종 궤적 결과가 있습니다. 이 상태에서는 재실행을 지원하지 않습니다.','GUIDED_VLA_RERUN_NOT_SUPPORTED')
                    context.decision_reason='GUIDED_VLA_ALREADY_READY'
                    return {'already_ready':True,**job.vla_prediction.model_dump(mode='json')}
            except AgentFault:
                raise
            except Exception:
                blocked('GUIDED_VLA_INPUT_CHANGED','현재 승인 마스크, 지시 또는 guidance 연결을 다시 확인해주세요.','GUIDED_VLA_INPUT_CHANGED')
            readiness=client.status()
            if not readiness.get('configured'):
                if backend=='gpt':
                    # Native status exposes a fixed reason code, never paths or exception payloads.
                    safe_codes={'GPT_TRAJECTORY_SOURCE_MISSING','GPT_TRAJECTORY_PYTHON_MISSING',
                        'GPT_TRAJECTORY_RETRIEVAL_DEPENDENCY_MISSING','GPT_TRAJECTORY_CONFIGURATION_INVALID',
                        'GPT_TRAJECTORY_TOKEN_REQUIRED'}
                    code=readiness.get('code')
                    code=code if code in safe_codes else 'GPT_TRAJECTORY_CONFIGURATION_INVALID'
                    message=('GPT native retrieval 의존성이 준비되지 않았습니다. Backend의 원본 모듈 복원이 필요합니다.'
                             if code=='GPT_TRAJECTORY_RETRIEVAL_DEPENDENCY_MISSING' else 'GPT 최종 궤적 predictor의 Backend 설정을 확인해주세요.')
                    blocked(code,message)
                blocked('GUIDED_VLA_BACKEND_NOT_CONFIGURED','Guided VLA 서버 설정이 필요합니다.')
            if job.state.value!='ROUGH_PATH_READY':
                blocked('GUIDED_VLA_GUIDANCE_REQUIRED','먼저 현재 조건의 Trajectory3 guidance를 준비해주세요.')
            context.completed['guided_vla']=True
            try:
                job=context.workflow.run_final_trajectory_prediction(job.id)
            finally:
                # Failed native output can still produce a display-only artifact.
                context.updated(context.workflow.get_job(job.id))
            return job.vla_prediction.model_dump(mode='json')
    return await context.call(name,lambda:context.work(operation))


async def route_final_trajectory_request(context):
    def inspect():
        job=context.job()
        context.remember(job)
        return workspace_summary(job)
    await context.call('get_workspace_state',lambda:context.work(inspect))
    if context.failures: raise context.failures[0]
    result=await final_prediction_request(context,generic=True)
    if context.failures: raise context.failures[0]
    source='GPT Trajectory · vlm_final_gpt' if result.get('source')=='vlm_final_gpt' else 'Guided VLA'
    if result.get('already_ready'):
        return f'이미 현재 승인 마스크와 guidance에 대한 {source} 결과가 있습니다. Simulator 패널에서 확인해주세요.'
    return f'{source}의 최종 3D 예측 궤적을 생성했습니다. 물리 로봇 실행은 비활성화되어 있습니다. Simulator 패널에서 Path Preview와 Robot Preview를 별도로 요청할 수 있습니다.'


TOOLS = [get_workspace_state, load_welding_scene, detect_weld_mask, auto_segment_weld_region, set_weld_instruction, create_current_weld_plan, create_weld_preview_plan,run_guided_vla,run_final_trajectory_prediction,
         get_simulator_status, start_simulator, run_existing_vla_sample, stop_simulator]

# Keep the historical callable for compatibility, but never offer predictor-specific
# execution to the orchestration model. Runtime selection belongs to Workflow.
SDK_TOOLS = [tool for tool in TOOLS if tool.name != 'run_guided_vla']
