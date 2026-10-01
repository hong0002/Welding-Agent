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


def invalid_arguments(ctx, _error):
    fault = AgentFault("tool_validation_error", "Agent 도구 입력 형식이 올바르지 않습니다.")
    ctx.context.failures.append(fault)
    ctx.context.emit("error", {"code": fault.code, "message": fault.message})
    return json.dumps({"ok": False, "code": fault.code, "message": fault.message}, ensure_ascii=False)


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
    ctx: RunContextWrapper[WeldingAgentContext], direction: Literal["left_to_right", "right_to_left"],
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
            try:
                job = context.workflow.plan(job.id, progress=progress)
            except Exception:
                if active_stage:
                    context.emit("tool_completed", {"tool": active_stage, "label": labels[active_stage] + " 실패",
                                 "call_id": f"{context.sequence}-{active_stage}", "success": False})
                context.updated(context.workflow.get_job(job.id))
                raise
            context.updated(job)
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
    context = ctx.context
    def segment():
        with context.storage.lock:
            context.authorize_segmentation()
            job = context.job(require_checked=True)
            if "segmentation" in context.completed:
                raise AgentFault("segmentation_already_attempted", "이번 요청에서 자동 검출을 이미 시도했습니다. 현재 결과를 확인하세요.")
            context.completed["segmentation"] = True
            job = context.workflow.set_mask(job.id, instruction=context.message)
            context.updated(job)
            return workspace_summary(job)
    return await context.call("auto_segment_weld_region", lambda: context.work(segment))


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
    context=ctx.context
    def operation():
        context.authorize_guided_vla()
        job=context.job(require_checked=True)
        if 'guided_vla' in context.completed:raise AgentFault('guided_vla_already_attempted','이번 요청에서 Guided VLA를 이미 시도했습니다.',409)
        context.completed['guided_vla']=True
        job=context.workflow.run_guided_vla(job.id);context.updated(job)
        return job.vla_prediction.model_dump(mode='json')
    return await context.call('run_guided_vla',lambda:context.work(operation))


TOOLS = [get_workspace_state, auto_segment_weld_region, set_weld_instruction, create_current_weld_plan, create_weld_preview_plan,run_guided_vla,
         get_simulator_status, start_simulator, run_existing_vla_sample, stop_simulator]
