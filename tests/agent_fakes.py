import asyncio
import json

from agents import RunConfig
from agents.tool_context import ToolContext

from backend.agent.tools import TOOLS


async def invoke(context, name, **arguments):
    tool = next(tool for tool in TOOLS if tool.name == name)
    args = json.dumps(arguments)
    wrapper = ToolContext(context=context, tool_name=name, tool_call_id=f"test-{context.sequence}",
                          tool_arguments=args, run_config=RunConfig(tracing_disabled=True, trace_include_sensitive_data=False))
    result = await tool.on_invoke_tool(wrapper, args)
    return json.loads(result) if isinstance(result, str) else result


class FakeSimulator:
    def __init__(self):
        self.state = "STOPPED"
        self.calls = []
        self.polls = 0

    def status(self):
        if self.state == "STARTING":
            self.polls += 1
            if self.polls >= 2:
                self.state = "READY"
        return {"state": self.state, "configured": True, "configuration_errors": [], "sample_configuration_errors": [],
                "error": None, "can_start": self.state == "STOPPED", "can_stop": self.state != "STOPPED",
                "can_run_sample": self.state == "READY", "sample_id": "offline-fixture", "latest_sample": None,
                "readiness": "offline test", "preview_connected": False, "robot_execution_enabled": False,
                "simulator_pid": None, "sample_pid": None, "session_dir": None, "sample_mode": "existing_vla_prediction"}

    def start(self):
        self.calls.append("start")
        self.state = "STARTING"
        return self.status()

    def run_sample(self):
        assert self.state == "READY"
        self.calls.append("run")
        self.state = "RUNNING_SAMPLE"
        return self.status()

    def stop(self):
        self.calls.append("stop")
        self.state = "STOPPED"
        return self.status()

    def logs(self):
        return {"entries": []}

    def close(self):
        pass


class FakeRunner:
    """Deterministic scenario fixture; actual semantic tools/workflow/storage still run."""
    def __init__(self):
        self.calls = 0
        self.memories = []

    async def run(self, context, session, settings):
        self.calls += 1
        self.memories.append(await session.get_items())
        await session.add_items([{"role": "user", "content": context.message}])
        await asyncio.sleep(0.05)
        if context.intent.run:
            await invoke(context, "get_simulator_status")
            await invoke(context, "start_simulator")
            await invoke(context, "run_existing_vla_sample")
            final = "기존 VLA 샘플 재생을 요청했습니다. 현재 웹 경로와는 별개입니다."
        else:
            state = await invoke(context, "get_workspace_state")
            if "내가 다시 표시" in context.message:
                final = "수동으로 다시 표시해주세요. 현재 마스크를 유지했습니다."
                await session.add_items([{"role": "assistant", "content": final}])
                return final
            if "자동으로 찾아" in context.message:
                state = await invoke(context, "auto_segment_weld_region")
            if not state["mask_ready"]:
                final = "RGB 이미지와 용접 마스크를 먼저 준비해주세요."
            else:
                previous = state["instruction"] or {}
                skip = previous.get("skip_regions", [])
                if "두 번째" in context.message:
                    skip = [state["regions"][1]["region_id"]]
                direction = "right_to_left" if "오른쪽에서 왼쪽" in context.message else previous.get("direction", "left_to_right")
                await invoke(context, "set_weld_instruction", direction=direction, start_region=None,
                             region_order=None, skip_regions=skip)
                await invoke(context, "create_current_weld_plan")
                final = "용접 경로를 생성했습니다. Preview geometry 검증을 통과했습니다."
        await session.add_items([{"role": "assistant", "content": final}])
        return final
