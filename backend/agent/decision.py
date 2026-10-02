"""Display-only decisions derived from intent and state, never model reasoning.

Only enums, booleans and bounded counts cross this event boundary. UI prose is
selected from fixed templates; user text and tool results are not summary data.
"""
from dataclasses import dataclass
from enum import Enum
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from backend.agent.mask_intent import MaskIntent
from backend.agent.scene_intent import scene_sample


class DecisionIntent(str, Enum):
    SCENE = 'scene_load'
    MASK = 'mask_detection'
    REMASK = 'mask_redetection'
    INSTRUCTION = 'instruction_update'
    ROUGH = 'rough_trajectory_generation'
    VLA = 'guided_vla_execution'
    PATH = 'simulator_path_preview'
    ROBOT = 'simulator_robot_preview'
    SIMULATOR = 'simulator_control'
    EXPLANATION = 'explanation'
    CLARIFICATION = 'clarification'
    PREPARATION = 'prerequisite_check'


@dataclass(frozen=True)
class RequestIntent:
    intent: DecisionIntent
    handled: bool = False
    rerun: bool = False
    preview_after: bool = False


def parse_request(message: str) -> RequestIntent:
    """Recognize request acts, not isolated VLA/trajectory keywords.

    Questions, negation, postponement and result inspection win over execution.
    Explicit generate-then-preview selects VLA only; preview remains a separate
    UI action. Unqualified robot/final requests require clarification.
    """
    text = message.lower().strip()
    compact = re.sub(r'\s+', '', text)
    vla = bool(re.search(r'(?<![a-z0-9])vla(?![a-z0-9])|3d|xyz', text) or
               re.search(r'(?:실제|최종).*궤적', compact))
    sim = bool(re.search(r'시뮬|simulat|isaac|robot\s*preview|path\s*preview|로봇.*(?:움직|미리보기)', text))
    non_execution = bool(re.search(
        r"하지\s*마|하지\s*말|말고|마세요|금지|않|안\s*(?:돼|된다)|나중|다음에|설명|방법|예시|뭐야|어때|왜|준비|상태|확인|"
        r"할\s*수|가능|do\s*not|don't|never|not\s+(?:run|predict|generate)|later|"
        r"explain|what|why|how|can\s+|could\s+|status|ready|inspect|"
        r"(?:서버|server).*(?:실행|시작|연결|launch|start)", text))
    readonly = non_execution or bool(re.search(r'보여|show',text))
    action = bool(re.search(
        r'(?:실행|생성|예측|계산|호출|정교화)(?:해(?:줘|주세요|라|요)?|하(?:자|세요|라)|시켜(?:줘|주세요))|'
        r'만들(?:어|자)|뽑아|돌려|(?:^|\b)(?:run|generate|predict|create|compute|refine)\b', text))
    # A simulator display request must not implicitly create a missing VLA.
    multi = bool(sim and re.search(r'(?:vla|3d|xyz).*?(?:생성|예측|만들).*?(?:후|다음|뒤|하고|해서|and then|then)', text))
    if re.search(r'기존.*샘플|existing.*sample|pre-existing.*sample', text) and not readonly:
        return RequestIntent(DecisionIntent.SIMULATOR)
    if sim and re.search(r'중지|종료|꺼|끄|시작|켜|stop|shutdown|start|launch', text) and not readonly:
        return RequestIntent(DecisionIntent.SIMULATOR)
    if sim and not multi:
        # Existing sample replay keeps its original explicit authorization path.
        legacy = bool(re.search(r'기존|existing|pre-existing', text) and re.search(r'샘플|sample', text))
        if not legacy and (action or re.search(r'보여|preview|show', text)) and not re.search(r"하지\s*마|하지\s*말|금지|don't|never", text):
            return RequestIntent(DecisionIntent.ROBOT if re.search(r'robot|로봇|움직', text) else DecisionIntent.PATH, True)
    if vla:
        if non_execution or '?' in text or (readonly and not multi):
            return RequestIntent(DecisionIntent.EXPLANATION, True)
        if action or multi:
            return RequestIntent(DecisionIntent.VLA, True, bool(re.search(r'다시|새로|재실행|rerun|again', text)), multi)
        return RequestIntent(DecisionIntent.EXPLANATION, True)
    if scene_sample(message):
        return RequestIntent(DecisionIntent.SCENE)
    mask = MaskIntent.parse(message)
    if mask.detect:
        return RequestIntent(DecisionIntent.REMASK if mask.redetect else DecisionIntent.MASK)
    if re.search(r'실제.*경로|로봇.*경로.*만들|최종으로.*해', compact):
        return RequestIntent(DecisionIntent.CLARIFICATION, True)
    if re.search(r'경로|궤적|trajectory|path|용접해|weld', text):
        return RequestIntent(DecisionIntent.ROUGH)
    return RequestIntent(DecisionIntent.INSTRUCTION if re.search(r'방향|제외|지시|instruction', text) else DecisionIntent.EXPLANATION)


class Prerequisite(BaseModel):
    model_config = ConfigDict(extra='forbid')
    key: Literal['scene', 'approved_f_mask', 'guidance', 'vla_backend', 'single_region', 'current_vla']
    ready: StrictBool


class AgentDecisionSummary(BaseModel):
    model_config = ConfigDict(extra='forbid')
    intent: DecisionIntent
    status: Literal['planned', 'running', 'completed', 'blocked', 'clarification']
    reason_code: Literal['USER_REQUESTED_ACTION', 'USER_REQUESTED_MASK_REDETECTION',
        'USER_REQUESTED_GUIDED_VLA_EXECUTION', 'USER_REQUESTED_TRAJECTORY_GENERATION',
        'GUIDED_VLA_PREREQUISITE_MISSING', 'GUIDED_VLA_ALREADY_READY',
        'GUIDED_VLA_RERUN_NOT_SUPPORTED', 'GUIDED_VLA_INPUT_CHANGED',
        'SIMULATOR_PREVIEW_INTENT', 'CLARIFICATION_REQUIRED', 'READ_ONLY_REQUEST',
        'ACTION_FAILED', 'NATIVE_OUTPUT_NOT_ACCEPTED', 'MASK_DRAFT_UNSAVED', 'MASK_APPROVAL_REQUIRED']
    selected_action: Literal['workspace', 'scene', 'segment2', 'instruction', 'trajectory3', 'guided_vla', 'simulator_panel', 'simulator_control', 'clarification']
    current_step: Literal['workspace', 'scene', 'segment2', 'instruction', 'trajectory3', 'guided_vla', 'rough', 'refine', 'validate', 'simulator', 'result']
    next_step: Literal['load_scene', 'detect_mask', 'approve_f_mask', 'generate_guidance', 'answer_question', 'run_vla', 'simulator_panel', 'review_result', 'check_configuration', 'check_inputs']
    prerequisites: list[Prerequisite] = Field(max_length=6)
    job_id: UUID | None = None
    view_count: int = Field(default=0, ge=0, le=9)
    point_count: int = Field(default=0, ge=0, le=100000)


ACTION = {
    DecisionIntent.SCENE: 'scene', DecisionIntent.MASK: 'segment2', DecisionIntent.REMASK: 'segment2',
    DecisionIntent.INSTRUCTION: 'instruction', DecisionIntent.ROUGH: 'trajectory3', DecisionIntent.VLA: 'guided_vla',
    DecisionIntent.PATH: 'simulator_panel', DecisionIntent.ROBOT: 'simulator_panel',
    DecisionIntent.SIMULATOR: 'simulator_control',
    DecisionIntent.EXPLANATION: 'workspace', DecisionIntent.CLARIFICATION: 'clarification',
    DecisionIntent.PREPARATION: 'workspace',
}
TOOL_STEP = {'load_welding_scene':'scene', 'detect_weld_mask':'segment2', 'auto_segment_weld_region':'segment2',
    'set_weld_instruction':'instruction', 'create_current_weld_plan':'trajectory3', 'create_weld_preview_plan':'trajectory3',
    'answer_trajectory_clarification':'trajectory3', 'run_guided_vla':'guided_vla',
    'rough':'rough', 'refine':'refine', 'validate':'validate', 'get_simulator_status':'simulator',
    'start_simulator':'simulator', 'run_existing_vla_sample':'simulator', 'stop_simulator':'simulator'}


def summarize(request, job, *, status='planned', tool=None, reason=None, backend_configured=False):
    mask = job.mask if job else None
    approved = bool(mask and mask.approved and (not job.scene.primary_view or job.scene.primary_view == 'F'))
    guidance = bool(job and job.rough3d and (not job.native_output or
                    (job.native_output.status=='NATIVE_OUTPUT_VALIDATED' and job.native_output.validation.status=='PASS')))
    ready_vla = bool(job and job.vla_prediction and job.state.value == 'VLA_READY')
    next_step = ('load_scene' if not job else 'detect_mask' if not mask else 'approve_f_mask' if not approved
                 else 'answer_question' if job.trajectory_clarification else 'simulator_panel' if ready_vla
                 else 'run_vla' if guidance else 'generate_guidance')
    default_reason = {DecisionIntent.REMASK:'USER_REQUESTED_MASK_REDETECTION', DecisionIntent.VLA:'USER_REQUESTED_GUIDED_VLA_EXECUTION',
        DecisionIntent.ROUGH:'USER_REQUESTED_TRAJECTORY_GENERATION', DecisionIntent.PATH:'SIMULATOR_PREVIEW_INTENT',
        DecisionIntent.ROBOT:'SIMULATOR_PREVIEW_INTENT', DecisionIntent.EXPLANATION:'READ_ONLY_REQUEST',
        DecisionIntent.CLARIFICATION:'CLARIFICATION_REQUIRED'}.get(request.intent, 'USER_REQUESTED_ACTION')
    if job and job.trajectory_clarification and status in ('planned','completed') and request.intent in (DecisionIntent.ROUGH, DecisionIntent.CLARIFICATION):
        status, reason = 'clarification', 'CLARIFICATION_REQUIRED'
    if request.intent == DecisionIntent.CLARIFICATION and request.handled and status != 'running':
        status, next_step = 'clarification', 'answer_question'
    if request.intent in (DecisionIntent.PATH, DecisionIntent.ROBOT):
        next_step = 'simulator_panel' if ready_vla else next_step
        if not ready_vla: status = 'blocked'
    if request.intent == DecisionIntent.SIMULATOR:next_step='review_result'
    if (job and job.native_output and not job.trajectory_clarification and status=='completed'
            and request.intent in (DecisionIntent.ROUGH,DecisionIntent.CLARIFICATION)
            and job.native_output.status!='NATIVE_OUTPUT_VALIDATED'):
        status,reason,next_step='blocked','NATIVE_OUTPUT_NOT_ACCEPTED','check_inputs'
    if status=='blocked' and reason=='GUIDED_VLA_INPUT_CHANGED': next_step='check_inputs'
    elif status=='blocked' and approved and guidance and not backend_configured: next_step='check_configuration'
    return AgentDecisionSummary(intent=request.intent, status=status, reason_code=reason or default_reason,
        selected_action=ACTION[request.intent], current_step=TOOL_STEP.get(tool, 'result' if status=='completed' else 'workspace'),
        next_step=next_step, job_id=job.id if job else None,
        prerequisites=[Prerequisite(key=k,ready=v) for k,v in [('scene',bool(job)),('approved_f_mask',approved),
            ('guidance',guidance),('vla_backend',backend_configured),('single_region',bool(mask and len(mask.regions)==1)),('current_vla',ready_vla)]],
        view_count=len(job.scene.views) if job else 0, point_count=job.vla_prediction.point_count if ready_vla else 0)
