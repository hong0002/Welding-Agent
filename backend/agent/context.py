import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Callable
from uuid import UUID

from backend.agent.config import AgentFault, public_error
from backend.agent.prompts import PREVIEW_LIMITATION
from backend.orchestrator.workflow import Workflow
from backend.services.simulator_client import SimulatorClient

LABELS = {
    "get_workspace_state": "작업 상태 확인", "set_weld_instruction": "용접 지시 적용",
    "create_weld_preview_plan": "용접 경로 생성 및 검증", "get_simulator_status": "Simulator 상태 확인",
    "start_simulator": "Simulator 준비", "run_existing_vla_sample": "기존 VLA 샘플 재생",
    "stop_simulator": "Simulator 중지",
    "auto_segment_weld_region": "용접 영역 자동 검출",
    "create_current_weld_plan": "현재 마스크로 경로 생성 및 검증",
}
logger = logging.getLogger("welding.agent")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s welding.agent %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False


@dataclass(frozen=True)
class SimulatorIntent:
    start: bool = False
    run: bool = False
    stop: bool = False
    current_preview: bool = False

    @classmethod
    def parse(cls, message: str):
        text = re.sub(r"\s+", "", message.lower())
        sim = bool(re.search(r"시뮬|simulat|isaac", text))
        preview = bool(re.search(r"경로|preview|plan|path", text))
        current = bool(re.search(r"현재|지금|방금|이번|웹|이경로|current|this|new", text))
        blocked = sim and preview and current
        negative = bool(re.search(r"하지마|하지말|말고|마세요|않|금지|don't|donot|never|방법|설명|예시|howto|example", text))
        if blocked or negative:
            return cls(current_preview=blocked)
        run = bool(re.search(r"기존|existing|pre-existing", text) and re.search(r"샘플|sample|vla", text)
                   and re.search(r"실행|재생|돌려|run|play", text))
        start = run or bool(sim and re.search(r"시작|켜|start|launch|turnon", text))
        stop = bool(sim and re.search(r"중지|종료|꺼|끄|stop|shutdown", text))
        return cls(start=start, run=run, stop=stop)


@dataclass
class WeldingAgentContext:
    job_id: UUID | None
    session_id: str
    message: str
    workflow: Workflow
    simulator: SimulatorClient
    emit: Callable[[str, dict], None]
    ready_timeout: float = 185
    checked: bool = False
    revision: str | None = None
    failures: list[AgentFault] = field(default_factory=list)
    completed: dict = field(default_factory=dict)
    sequence: int = 0
    pending: set = field(default_factory=set)
    active: bool = True
    tool_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def work(self, operation):
        if not self.active:
            raise AgentFault("run_closed", "종료된 Agent 요청입니다.")
        # Cancellation cannot release the job lease while a synchronous mutation still runs.
        task = asyncio.create_task(asyncio.to_thread(operation))
        self.pending.add(task)
        def settled(done):
            self.pending.discard(done)
            if not done.cancelled():
                done.exception()  # Also observe errors if the waiting tool was cancelled.
        task.add_done_callback(settled)
        return await asyncio.shield(task)

    @property
    def storage(self):
        return self.workflow.storage

    @property
    def intent(self):
        return SimulatorIntent.parse(self.message)

    def job(self, require_checked=False):
        if self.job_id is None:
            raise AgentFault("workspace_missing", "먼저 RGB 이미지를 업로드하고 용접 영역을 지정해주세요.")
        job = self.workflow.get_job(self.job_id)
        if require_checked and (not self.checked or str(job.updated_at) != self.revision):
            raise AgentFault("workspace_changed", "작업 상태가 변경되었습니다. get_workspace_state로 다시 확인하세요.", 409)
        return job

    def remember(self, job):
        self.checked = True
        self.revision = str(job.updated_at)

    def authorize(self, action: str):
        if self.intent.current_preview:
            raise AgentFault("preview_not_connected", PREVIEW_LIMITATION)
        if not getattr(self.intent, action):
            raise AgentFault("simulator_intent_required", "Simulator 동작은 이번 메시지의 명시적인 실행 요청이 필요합니다.", 403)

    def authorize_segmentation(self):
        text = re.sub(r"\s+", "", self.message.lower())
        manual = re.search(r"내가.*(?:그린|표시|그릴)|직접.*(?:그릴|표시)|표시한영역|표시한부분|manual|drawn", text)
        negative = re.search(r"하지마|하지말|말고|마세요|금지|don't|donot|never|설명|예시|방법|howto|example", text)
        automatic = re.search(r"자동.*(?:찾|검출|선택|탐지)|ai로.*(?:찾|검출|선택)|용접영역찾|용접할부분.*찾|auto.*(?:detect|segment|find)|find.*weld", text)
        if manual or negative or not automatic:
            raise AgentFault("segmentation_intent_required", "자동 영역 검출은 이번 메시지의 명시적인 요청이 필요합니다. 현재 마스크를 유지했습니다.", 403)

    def authorize_workspace_mutation(self):
        text = re.sub(r"\s+", "", self.message.lower())
        if re.search(r"(?:내가|직접).*(?:다시표시할|다시그릴)|i(?:'ll|will).*redraw", text):
            raise AgentFault("manual_edit_pending", "직접 수정할 마스크를 기다립니다. 현재 결과를 변경하지 않았습니다.", 409)

    async def call(self, name, operation):
        # Defend against a model emitting parallel calls despite parallel_tool_calls=False.
        async with self.tool_lock:
            if not self.active:
                raise AgentFault("run_closed", "종료된 Agent 요청입니다.")
            return await self._call(name, operation)

    async def _call(self, name, operation):
        self.sequence += 1
        call_id = str(self.sequence)
        label = LABELS[name]
        self.emit("tool_started", {"tool": name, "label": label, "call_id": call_id})
        started = time.monotonic()
        success = False
        try:
            result = await operation()
            if name == "auto_segment_weld_region":
                label += f" 완료 · {len(result['regions'])} regions · {result['mask_source']}"
            self.emit("tool_completed", {"tool": name, "label": label, "call_id": call_id, "success": True})
            success = True
            return result
        except Exception as exc:
            if name in ("get_simulator_status", "start_simulator", "run_existing_vla_sample", "stop_simulator") and not isinstance(exc, AgentFault):
                fault = AgentFault("simulator_error", "Simulator 요청에 실패했습니다. Simulator 탭에서 설정과 실행 로그를 확인하세요.", 503)
            else:
                fault = public_error(exc)
            self.failures.append(fault)
            self.emit("tool_completed", {"tool": name, "label": label, "call_id": call_id,
                                         "success": False, "message": fault.message, "code": fault.code})
            success = False
            return {"ok": False, "code": fault.code, "message": fault.message}
        finally:
            logger.info("session=%s job=%s tool=%s success=%s latency_ms=%d", self.session_id, self.job_id,
                        name, success, int((time.monotonic() - started) * 1000))

    def updated(self, job):
        self.remember(job)
        self.emit("workspace_updated", {"job_id": str(job.id)})


def workspace_summary(job):
    if job is None:
        return {"job_state": "EMPTY", "scene_ready": False, "mask_ready": False, "regions": [],
                "instruction": None, "rough_ready": False, "final_ready": False, "validation": None}
    skip = job.instruction.structured.skip_regions if job.instruction else []
    return {
        "job_state": job.state.value, "scene_ready": job.scene is not None, "mask_ready": job.mask is not None,
        "mask_source": job.mask.mask_source if job.mask else None,
        "regions": [{**r.model_dump(), "selected": r.region_id not in skip} for r in job.mask.regions] if job.mask else [],
        "instruction": job.instruction.structured.model_dump() if job.instruction else None,
        "rough_ready": job.rough_trajectory is not None, "final_ready": job.final_trajectory is not None,
        "validation": {"valid": job.validation.valid, "scope": "preview_geometry_only"} if job.validation else None,
        "coordinate_space": "image_pixel", "is_robot_executable": False,
    }


def simulator_summary(status):
    return {"state": status["state"], "sample_id": status.get("sample_id"),
            "can_start": bool(status.get("can_start")), "can_run_sample": bool(status.get("can_run_sample")),
            "can_stop": bool(status.get("can_stop")), "preview_connected": False,
            "latest_sample": {"status": status["latest_sample"]["status"]} if status.get("latest_sample") else None}
