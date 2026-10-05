import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Callable
from uuid import UUID

from backend.agent.config import AgentFault, public_error
from backend.agent.prompts import PREVIEW_LIMITATION
from backend.agent.mask_intent import MaskIntent
from backend.agent.decision import parse_request, summarize, DecisionIntent, RequestIntent
from backend.orchestrator.workflow import Workflow
from backend.services.simulator_client import SimulatorClient

LABELS = {
    'answer_trajectory_clarification':'Trajectory3 추가 답변 처리',
    'load_welding_scene':'9-view Scene 불러오기',
    'detect_weld_mask':'용접 마스크 검출',
    'run_guided_vla':'Guided VLA 예측',
    'run_final_trajectory_prediction':'최종 3D 궤적 예측',
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
    claim_job: Callable | None = None
    additional_jobs: set = field(default_factory=set)
    expected_clarification_id: UUID | None = None
    decision_job: object = None
    decision_reason: str | None = None
    decision_override: RequestIntent | None = None

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

    @property
    def mask_intent(self):
        return MaskIntent.parse(self.message)

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
        self.decision_job = job

    @property
    def request_intent(self):
        return parse_request(self.message)

    def decision(self, status='planned', tool=None, reason=None):
        try:
            self._emit_decision(status,tool,reason)
        except Exception:
            # Display-only reporting must not change tool admission or strand a
            # job/session lease. Never log the exception payload or native data.
            logger.warning('decision_summary_unavailable')

    def _emit_decision(self, status, tool, reason):
        if reason:
            self.decision_reason = reason
        client = self.workflow.final_predictor
        predictor_status = client.status() if client else {}
        configured = bool(predictor_status.get('configured'))
        predictor = 'gpt' if predictor_status.get('backend') == 'gpt' else 'guided_vla'
        if self.expected_clarification_id:
            self.decision_override=RequestIntent(DecisionIntent.CLARIFICATION)
        elif not self.request_intent.handled:
            intent={'answer_trajectory_clarification':DecisionIntent.CLARIFICATION,
                'create_current_weld_plan':DecisionIntent.ROUGH,'create_weld_preview_plan':DecisionIntent.ROUGH,
                'detect_weld_mask':DecisionIntent.MASK,'auto_segment_weld_region':DecisionIntent.MASK}.get(tool)
            if intent and not (intent==DecisionIntent.MASK and self.request_intent.intent in (DecisionIntent.MASK,DecisionIntent.REMASK)):
                self.decision_override=RequestIntent(intent)
        summary = summarize(self.decision_override or self.request_intent, self.decision_job, status=status, tool=tool,
                            reason=self.decision_reason, backend_configured=configured, final_predictor=predictor)
        self.emit('decision_summary', summary.model_dump(mode='json'))

    def adopt_job(self, job):
        if job.id != self.job_id:
            if self.claim_job:
                self.claim_job(job.id)
                self.additional_jobs.add(job.id)
            self.job_id = job.id
        self.updated(job)

    def authorize(self, action: str):
        if self.intent.current_preview:
            raise AgentFault("preview_not_connected", PREVIEW_LIMITATION)
        if not getattr(self.intent, action):
            raise AgentFault("simulator_intent_required", "Simulator 동작은 이번 메시지의 명시적인 실행 요청이 필요합니다.", 403)

    def authorize_segmentation(self):
        if not self.mask_intent.detect:
            raise AgentFault("segmentation_intent_required", "자동 영역 검출은 이번 메시지의 명시적인 요청이 필요합니다. 현재 마스크를 유지했습니다.", 403)

    def authorize_workspace_mutation(self):
        if self.job_id and self.job().trajectory_clarification:
            raise AgentFault('clarification_required','현재 native 질문에 먼저 답해주세요. 승인 마스크를 유지했습니다.',409)
        text = re.sub(r"\s+", "", self.message.lower())
        if self.mask_intent.detect:
            raise AgentFault('mask_detection_turn','마스크 검출 후 F Canvas를 확인하고 확정하세요. 경로 생성은 승인 후 요청해주세요.',409)
        if re.search(r"(?:내가|직접).*(?:다시표시할|다시그릴)|i(?:'ll|will).*redraw", text):
            raise AgentFault("manual_edit_pending", "직접 수정할 마스크를 기다립니다. 현재 결과를 변경하지 않았습니다.", 409)

    def authorize_guided_vla(self):
        if self.request_intent.intent != DecisionIntent.VLA:
            raise AgentFault('guided_vla_intent_required','최종 궤적 예측은 이번 메시지의 명시적인 실행 요청이 필요합니다.',403)

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
        if name == 'run_final_trajectory_prediction':
            client = self.workflow.final_predictor
            label = ('GPT 최종 3D 궤적 예측' if client and client.status().get('backend') == 'gpt'
                     else 'Guided VLA 예측')
        self.emit("tool_started", {"tool": name, "label": label, "call_id": call_id})
        self.decision('running', name)
        started = time.monotonic()
        success = False
        try:
            result = await operation()
            if name == "auto_segment_weld_region":
                label += f" 완료 · {len(result['regions'])} regions · {result['mask_source']}"
            elif name == 'detect_weld_mask':
                label += f" 완료 · {sum(result['region_count'].values())} regions · 승인 필요"
            elif name in ('create_current_weld_plan','create_weld_preview_plan') and result.get('native_output_generated'):
                label = '모델 경로 생성 완료 · ' + ('검증 통과' if result['validation_status']=='PASS' else '검증 미통과')
            elif name in ('create_current_weld_plan','create_weld_preview_plan') and result.get('clarification_required'):
                label = 'Native 질문 · 사용자 응답 대기'
            self.emit("tool_completed", {"tool": name, "label": label, "call_id": call_id, "success": True})
            self.decision('running', name)
            success = True
            return result
        except Exception as exc:
            if name in ("get_simulator_status", "start_simulator", "run_existing_vla_sample", "stop_simulator") and not isinstance(exc, AgentFault):
                fault = AgentFault("simulator_error", "Simulator 요청에 실패했습니다. Simulator 탭에서 설정과 실행 로그를 확인하세요.", 503)
            else:
                fault = public_error(exc)
            self.failures.append(fault)
            self.decision('blocked', name, self.decision_reason or 'ACTION_FAILED')
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


def rough_summary(rough):
    """Counts and availability only; native plans/Markdown never enter Agent context."""
    if rough is None:
        return None
    files = rough.artifact.provenance.native_artifacts if rough.artifact else {}
    return {"status": "ready", "regions": [s.region_id for s in rough.segments],
            "segment_count": len(rough.segments), "point_count": sum(len(s.points) for s in rough.segments),
            "coordinate_space": rough.coordinate_space, "units": rough.units,
            "frame": "image_top_left_x_right_y_down", "is_robot_executable": False,
            "cot_ko_available": files.get("iteration_001/cot_ko.md", False),
            "vla_prompt_available": files.get("iteration_001/vla_prompt.md", False)}


def workspace_summary(job):
    if job is None:
        return {"job_state": "EMPTY", "scene_ready": False, "mask_ready": False, "regions": [],
                "instruction": None, "rough_ready": False, "final_ready": False, "validation": None}
    from backend.model_clients.native_candidate import summary
    skip = job.instruction.structured.skip_regions if job.instruction else []
    return {
        "job_state": job.state.value, "scene_ready": job.scene is not None, "mask_ready": bool(job.mask and job.mask.approved),
        "mask_approval_required": bool(job.mask and not job.mask.approved),
        "mask_source": job.mask.mask_source if job.mask else None,
        "regions": [{**r.model_dump(), "selected": r.region_id not in skip} for r in job.mask.regions] if job.mask else [],
        "instruction": job.instruction.structured.model_dump() if job.instruction else None,
        "rough_ready": job.rough_trajectory is not None, "final_ready": job.final_trajectory is not None,
        "rough_summary": rough_summary(job.rough_trajectory),
        "native_output":summary(job.native_output),
        "segment_output":summary(job.raw_segment_output),
        "clarification_required":job.trajectory_clarification is not None,
        "clarification_question":job.trajectory_clarification.question if job.trajectory_clarification else None,
        "planning_status":job.planning_status,
        "sample_id": job.scene.sample_id if job.scene else None,
        "scene_views": list(job.scene.views) if job.scene else [],
        "rough_mode":job.rough_mode,
        "vla_ready":job.vla_prediction is not None,
        "vla_summary":job.vla_prediction.model_dump(mode='json') if job.vla_prediction else None,
        "simulator_ready":False,
        "validation": {"valid": job.validation.valid, "scope": "preview_geometry_only"} if job.validation else None,
        "coordinate_space": "image_pixel", "is_robot_executable": False,
    }


def simulator_summary(status):
    return {"state": status["state"], "sample_id": status.get("sample_id"),
            "can_start": bool(status.get("can_start")), "can_run_sample": bool(status.get("can_run_sample")),
            "can_stop": bool(status.get("can_stop")), "preview_connected": False,
            "latest_sample": {"status": status["latest_sample"]["status"]} if status.get("latest_sample") else None}
