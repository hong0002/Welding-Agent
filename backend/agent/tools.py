"""Only semantic operations are exposed to the model; never paths, commands or points."""
import asyncio
import json
import time
from typing import Literal

from agents import RunContextWrapper, function_tool

from backend.agent.config import AgentFault
from backend.agent.context import WeldingAgentContext, simulator_summary, workspace_summary
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


@function_tool(failure_error_function=invalid_arguments)
async def create_weld_preview_plan(ctx: RunContextWrapper[WeldingAgentContext]) -> dict:
    """Run the backend's deterministic rough → VLA → geometry validation pipeline.
    Requires a confirmed mask and applied instruction. Returns counts/regions only, never waypoints.
    A validated image_pixel preview is not robot executable and never starts simulation.
    """
    context = ctx.context
    def plan():
        with context.storage.lock:
            job = context.job(require_checked=True)
            job = context.workflow.plan(job.id)
            context.updated(job)
            rough = sum(len(s.points) for s in job.rough_trajectory.segments)
            final = sum(len(s.points) for s in job.final_trajectory.segments)
            for name, label in (("rough", f"Rough path 생성 · {rough} pts"),
                                ("refine", f"VLA refinement · {final} pts"),
                                ("validate", "Preview validation 통과")):
                context.emit("tool_completed", {"tool": name, "label": label,
                                               "call_id": f"{context.sequence}-{name}", "success": True})
            return {"state": job.state.value, "regions": [s.region_id for s in job.final_trajectory.segments],
                    "rough_points": rough, "final_points": final, "validation_passed": job.validation.valid,
                    "coordinate_space": "image_pixel", "is_robot_executable": False}
    return await context.call("create_weld_preview_plan", lambda: context.work(plan))


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


TOOLS = [get_workspace_state, set_weld_instruction, create_weld_preview_plan,
         get_simulator_status, start_simulator, run_existing_vla_sample, stop_simulator]
