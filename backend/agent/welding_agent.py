import logging
from typing import Protocol

from backend.agent.config import AgentSettings
from backend.agent.context import WeldingAgentContext
from backend.agent.prompts import INSTRUCTIONS


class AgentRunner(Protocol):
    async def run(self, context: WeldingAgentContext, session, settings: AgentSettings) -> str: ...


class SDKRunner:
    semantic_selection = True
    def __init__(self, *, model_override=None):
        # Constructor-only injection for offline tests; never exposed through HTTP or environment.
        self.model_override = model_override

    async def run(self, context, session, settings):
        context.semantic_selection = True
        from agents import Agent, ModelSettings, OpenAIResponsesModel, RunConfig, Runner, set_tracing_disabled
        from openai import AsyncOpenAI
        from openai.types.shared import Reasoning
        from backend.agent.tools import SDK_TOOLS
        from backend.agent.semantic_tools import SEMANTIC_TOOLS

        set_tracing_disabled(True)
        for name in ("openai", "openai.agents", "httpx", "httpcore", "httpx2", "httpcore2"):
            logging.getLogger(name).setLevel(logging.CRITICAL)
        client = None
        result = None
        try:
            model = self.model_override
            if model is None:
                client = AsyncOpenAI(api_key=settings.api_key, base_url="https://api.openai.com/v1",
                                     timeout=45, max_retries=0)
                model = OpenAIResponsesModel(settings.model, client)
            tools=[t for t in SDK_TOOLS if t.name not in ('auto_segment_weld_region','create_weld_preview_plan','create_current_weld_plan')]+SEMANTIC_TOOLS
            agent = Agent(name="WeldingOrchestrator", instructions=INSTRUCTIONS, model=model, tools=tools,
                          model_settings=ModelSettings(parallel_tool_calls=False, verbosity="low", store=False,
                                                       reasoning=Reasoning(effort=settings.reasoning_effort)))
            result = Runner.run_streamed(agent, context.message, context=context, session=session,
                                         max_turns=settings.max_turns,
                                         run_config=RunConfig(tracing_disabled=True, trace_include_sensitive_data=False))
            async for _event in result.stream_events():
                # Tool wrappers emit allowlisted progress. Raw SDK events/reasoning never reach UI.
                # Buffer final text so even secrets split across token chunks can be redacted.
                pass
            logging.getLogger("welding.agent").info("session=%s tokens=%s", context.session_id,
                                                     result.context_wrapper.usage.total_tokens)
            return str(result.final_output or "요청을 처리했습니다.")
        finally:
            context.active = False
            if result is not None and not result.is_complete:
                result.cancel()
                async for _event in result.stream_events():
                    pass
            if context.pending:
                import asyncio
                await asyncio.gather(*context.pending, return_exceptions=True)
            if client:
                await client.close()
