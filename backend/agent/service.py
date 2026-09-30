import asyncio
import json
import logging
import threading
import time
from contextlib import contextmanager

from backend.agent.config import AgentFault, AgentSettings, public_error, redact
from backend.agent.context import WeldingAgentContext
from backend.agent.prompts import PREVIEW_LIMITATION
from backend.agent.sessions import SessionStore
from backend.agent.welding_agent import SDKRunner

EVENT_FIELDS = {
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

    async def begin(self, sid, job_id, message):
        status = self.settings.status()
        if status["state"] != "READY":
            raise AgentFault("agent_not_configured", "GPT Agent 설정이 필요합니다. 수동 지시와 Path 기능은 계속 사용할 수 있습니다.", 503)
        self.sessions.get(sid)
        self._claim(sid, job_id)
        try:
            if job_id:
                await asyncio.to_thread(self.workflow.get_job, job_id)
        except BaseException as exc:
            self._release(sid, job_id)
            if isinstance(exc, Exception):
                raise public_error(exc) from None
            raise
        self._session_locks.setdefault(sid, asyncio.Lock())
        queue = asyncio.Queue()
        task = asyncio.create_task(self._drive(sid, job_id, message, queue))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return queue

    async def _drive(self, sid, job_id, message, queue):
        started = time.monotonic()
        loop = asyncio.get_running_loop()
        def emit(event, data):
            if event not in EVENT_FIELDS:
                return
            safe = {key: redact(value, self.settings.api_key) if isinstance(value, str) else value
                    for key, value in data.items() if key in EVENT_FIELDS[event]}
            loop.call_soon_threadsafe(queue.put_nowait, (event, safe))
        context = WeldingAgentContext(job_id, sid, redact(message, self.settings.api_key), self.workflow,
                                      self.simulator, emit, ready_timeout=self.settings.ready_timeout)
        memory = None
        ok = False
        try:
            # Atomic admission above rejects duplicates; this lock owns this session run until settled.
            async with self._session_locks[sid]:
                self.sessions.append(sid, "user", context.message)
                memory = self.sessions.sdk_session(sid, job_id)
                if context.intent.current_preview:
                    final = PREVIEW_LIMITATION
                    await memory.add_items([{"role": "user", "content": context.message},
                                            {"role": "assistant", "content": final}])
                    emit("warning", {"code": "preview_not_connected", "message": final})
                else:
                    final = await asyncio.wait_for(self.runner.run(context, memory, self.settings),
                                                   timeout=self.settings.run_timeout)
                    if context.failures:
                        raise context.failures[0]
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
        finally:
            context.active = False
            if context.pending:
                await asyncio.gather(*context.pending, return_exceptions=True)
            if memory:
                memory.close()
            # A partial plan may have saved a rough trajectory before a tool failed.
            if job_id:
                emit("workspace_updated", {"job_id": str(job_id)})
            self._release(sid, job_id)
            emit("done", {"ok": ok, "session_id": sid, "job_id": str(job_id) if job_id else None})
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
