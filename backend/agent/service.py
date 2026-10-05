import asyncio
import json
import logging
import re
import threading
import time
from contextlib import contextmanager

from backend.agent.config import AgentFault, AgentSettings, public_error, redact
from backend.agent.context import WeldingAgentContext
from backend.agent.decision import AgentDecisionSummary, DecisionIntent
from backend.agent.prompts import PREVIEW_LIMITATION
from backend.agent.sessions import SessionStore
from backend.agent.welding_agent import SDKRunner

EVENT_FIELDS = {
    'decision_summary': set(AgentDecisionSummary.model_fields),
    "assistant_delta": {"text"}, "tool_started": {"tool", "label", "call_id"},
    "tool_completed": {"tool", "label", "call_id", "success", "message", "code"},
    "workspace_updated": {"job_id"}, "warning": {"code", "message"}, "error": {"code", "message"},
    "done": {"ok", "session_id", "job_id"},
}


class AgentService:
    def __init__(self, workflow, simulator, *, settings=None, runner=None):
        self.workflow, self.simulator = workflow, simulator
        self.settings = settings or AgentSettings.from_env()
        self.runner = runner or SDKRunner()
        self.sessions = SessionStore(workflow.storage.root / "agent_sessions.db")
        self._guard = threading.Lock()
        self._jobs, self._sessions = set(), set()
        self._tasks = set()
        self._session_locks = {}

    def status(self):
        status = self.settings.status()
        with self._guard:
            if self._sessions and status["state"] == "READY":
                status["state"] = "RUNNING"
        return status

    def history(self, sid):
        result = self.sessions.history(sid)
        with self._guard:
            result["running"] = sid in self._sessions
        return result

    def _claim(self, sid=None, job_id=None):
        with self._guard:
            if (sid and sid in self._sessions) or (job_id and job_id in self._jobs):
                raise AgentFault("run_in_progress", "이 대화 또는 작업에서 요청이 실행 중입니다. 완료 후 다시 시도하세요.", 409)
            if sid:
                self._sessions.add(sid)
            if job_id:
                self._jobs.add(job_id)

    def _release(self, sid=None, job_id=None):
        with self._guard:
            self._sessions.discard(sid)
            self._jobs.discard(job_id)

    @contextmanager
    def manual_mutation(self, job_id):
        self._claim(job_id=job_id)
        try:
            yield
        finally:
            self._release(job_id=job_id)

    async def reset(self, sid):
        self._claim(sid=sid)
        try:
            await self.sessions.reset(sid)
            return self.history(sid)
        finally:
            self._release(sid=sid)

    async def begin(self, sid, job_id, message, clarification_id=None):
        status = self.settings.status()
        if status["state"] != "READY":
            raise AgentFault("agent_not_configured", "GPT Agent 설정이 필요합니다. 수동 지시와 Path 기능은 계속 사용할 수 있습니다.", 503)
        self.sessions.get(sid)
        self._claim(sid, job_id)
        try:
            if job_id:
                await asyncio.to_thread(self.workflow.admit_job, job_id)
        except BaseException as exc:
            self._release(sid, job_id)
            if isinstance(exc, Exception):
                raise public_error(exc) from None
            raise
        self._session_locks.setdefault(sid, asyncio.Lock())
        queue = asyncio.Queue()
        task = asyncio.create_task(self._drive(sid, job_id, message, queue, clarification_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return queue

    async def _drive(self, sid, job_id, message, queue, clarification_id=None):
        started = time.monotonic()
        loop = asyncio.get_running_loop()
        def emit(event, data):
            if event not in EVENT_FIELDS:
                return
            if event == 'decision_summary':
                try: safe = AgentDecisionSummary.model_validate(data).model_dump(mode='json')
                except ValueError: return
                loop.call_soon_threadsafe(queue.put_nowait, (event, safe))
                return
            safe = {key: redact(value, self.settings.api_key) if isinstance(value, str) else value
                    for key, value in data.items() if key in EVENT_FIELDS[event]}
            loop.call_soon_threadsafe(queue.put_nowait, (event, safe))
        context = WeldingAgentContext(job_id, sid, redact(message, self.settings.api_key), self.workflow,
                                      self.simulator, emit, ready_timeout=self.settings.ready_timeout)
        context.claim_job=lambda target:self._claim(job_id=target)
        context.expected_clarification_id=clarification_id
        # A class capability marker avoids triggering a fake Runner's dynamic
        # __getattr__ outside the error/lease cleanup boundary.
        context.semantic_selection=getattr(type(self.runner),'semantic_selection',False) is True
        memory = None
        ok = False
        try:
            # Atomic admission above rejects duplicates; this lock owns this session run until settled.
            async with self._session_locks[sid]:
                self.sessions.append(sid, "user", context.message)
                memory = self.sessions.sdk_session(sid, job_id)
                from backend.agent.scene_intent import scene_sample
                current = await context.work(context.job) if context.job_id else None
                if current: context.remember(current)
                context.decision()
                request=context.request_intent
                if clarification_id is not None or (not context.semantic_selection and current and current.trajectory_clarification
                        and not scene_sample(context.message) and not context.mask_intent.detect and not request.handled):
                    from backend.agent.tools import route_clarification_request
                    final = await asyncio.wait_for(route_clarification_request(context), timeout=self.settings.run_timeout)
                    await memory.add_items([{'role':'user','content':context.message},{'role':'assistant','content':final}])
                elif context.semantic_selection:
                    # Native question receipts remain explicit; all ordinary natural
                    # language task selection is owned by the SDK Orchestrator.
                    final=await asyncio.wait_for(self.runner.run(context,memory,self.settings),timeout=self.settings.run_timeout)
                    if context.failures:raise context.failures[0]
                elif request.intent == DecisionIntent.VLA:
                    from backend.agent.tools import route_final_trajectory_request
                    final=await asyncio.wait_for(route_final_trajectory_request(context),timeout=self.settings.run_timeout)
                    await memory.add_items([{'role':'user','content':context.message},{'role':'assistant','content':final}])
                elif request.handled:
                    if request.intent == DecisionIntent.CLARIFICATION:
                        final='최종 3D 궤적을 생성할까요, 아니면 현재 궤적을 시뮬레이터에서 확인할까요?'
                    elif request.intent in (DecisionIntent.PATH,DecisionIntent.ROBOT):
                        if current and current.vla_prediction and current.state.value=='VLA_READY':
                            final='현재 최종 3D 궤적 결과를 Simulator 패널에서 확인하세요. Path Preview 후 Robot Preview를 별도로 요청할 수 있습니다. 채팅에서 자동 실행하지 않았습니다.'
                        else:
                            final='현재 최종 3D 궤적 결과가 필요합니다. 승인된 F 마스크와 Trajectory3 guidance를 준비한 뒤 최종 궤적 생성을 명시적으로 요청해주세요. 자동 생성하지 않았습니다.'
                        emit('warning',{'code':'preview_not_connected','message':final})
                    else:
                        predictor=context.workflow.final_predictor
                        status=predictor.status() if predictor else {}
                        label='GPT Trajectory · vlm_final_gpt' if status.get('backend')=='gpt' else 'Guided VLA'
                        model=status.get('model')
                        # Never copy arbitrary status text/config paths into chat.
                        model_label=f' · 모델 {model}' if isinstance(model,str) and re.fullmatch(r'[a-zA-Z0-9_.-]{1,80}',model) else ''
                        final=(f'현재 최종 3D predictor는 {label}{model_label}입니다. Agent는 도구 선택과 workflow를 제어하며 XYZ를 생성하지 않습니다. '
                               + ('현재 최종 궤적 결과가 있습니다.' if current and current.vla_prediction else '현재 최종 궤적 결과는 없습니다.')
                               + ' 설명·상태·결과 확인 요청으로 처리했으며 inference를 호출하지 않았습니다.')
                    await memory.add_items([{'role':'user','content':context.message},{'role':'assistant','content':final}])
                elif context.intent.current_preview:
                    final = PREVIEW_LIMITATION
                    await memory.add_items([{"role": "user", "content": context.message},
                                            {"role": "assistant", "content": final}])
                    emit("warning", {"code": "preview_not_connected", "message": final})
                elif sample := scene_sample(context.message):
                    from backend.agent.tools import load_scene_request
                    result=await asyncio.wait_for(load_scene_request(context,sample),timeout=self.settings.run_timeout)
                    if context.failures:raise context.failures[0]
                    final=f"{result['sample_id']}의 9개 view를 불러왔습니다. 용접 영역 검출을 요청해주세요."
                    await memory.add_items([{'role':'user','content':context.message},{'role':'assistant','content':final}])
                elif context.mask_intent.detect:
                    # Route explicit mask intent before any model planning tool. Shared
                    # semantic tool still owns validation, serialization and mutation.
                    from backend.agent.tools import route_mask_request
                    final = await asyncio.wait_for(route_mask_request(context), timeout=self.settings.run_timeout)
                    await memory.add_items([{'role':'user','content':context.message},
                                            {'role':'assistant','content':final}])
                else:
                    final = await asyncio.wait_for(self.runner.run(context, memory, self.settings),
                                                   timeout=self.settings.run_timeout)
                    # Native questions are authoritative, including a first
                    # clarification produced during ordinary planning.
                    # SDKRunner closes tool admission in its finally block.
                    # This final read is service-owned, not another model tool.
                    current = await asyncio.to_thread(context.job) if context.job_id else None
                    if context.failures and not (current and current.trajectory_clarification
                            and all(f.code == 'clarification_required' for f in context.failures)):
                        raise context.failures[0]
                    if current and current.trajectory_clarification:
                        from backend.orchestrator.clarification import message as clarification_message
                        final = clarification_message(current.trajectory_clarification)
                        await memory.add_items([{'role':'assistant','content':final}])
                if context.semantic_selection and context.job_id:
                    current=await asyncio.to_thread(context.job)
                    context.decision_job=current
                    if current.trajectory_clarification:
                        from backend.orchestrator.clarification import message as clarification_message
                        final=clarification_message(current.trajectory_clarification)
                    elif getattr(context,'safe_clarification_question',None):
                        final=context.safe_clarification_question
                final = redact(final, self.settings.api_key)
                self.sessions.append(sid, "assistant", final)
                emit("assistant_delta", {"text": final})
                ok = True
        except Exception as exc:
            fault = public_error(exc)
            safe_message = redact(fault.message, self.settings.api_key)
            self.sessions.append(sid, "assistant", safe_message)
            emit("error", {"code": fault.code, "message": safe_message})
            emit("assistant_delta", {"text": safe_message})
            context.decision('blocked', reason=context.decision_reason or 'ACTION_FAILED')
        finally:
            context.active = False
            if context.pending:
                await asyncio.gather(*context.pending, return_exceptions=True)
            if memory:
                memory.close()
            # A partial plan may have saved a rough trajectory before a tool failed.
            if context.job_id:
                emit("workspace_updated", {"job_id": str(context.job_id)})
                try:
                    context.decision_job = await asyncio.to_thread(context.job)
                except Exception: pass
            context.decision('completed' if ok else 'blocked')
            self._release(sid, job_id)
            for adopted in context.additional_jobs:self._release(job_id=adopted)
            emit("done", {"ok": ok, "session_id": sid, "job_id": str(context.job_id) if context.job_id else None})
            logging.getLogger("welding.agent").info("session=%s job=%s model=%s success=%s latency_ms=%d",
                sid, job_id, self.settings.model, ok, int((time.monotonic() - started) * 1000))

    async def stream(self, queue):
        # Disconnecting the browser does not release a still-running job lease or replay a tool.
        while True:
            try:
                event, data = await asyncio.wait_for(queue.get(), timeout=15)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            if event == "done":
                return

    async def close(self):
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
