"""Explicit native questions and human replies. Never reads native reasoning fields."""
import json
import re
from uuid import uuid4

from backend.schemas import TrajectoryClarification
from backend.orchestrator.state_machine import WorkflowError


class ClarificationError(WorkflowError):
    """Allowlisted public reason, never a native exception/prompt/path."""
    MESSAGES = {
        'CLARIFICATION_STALE': '현재 질문이 변경됐습니다. 작업을 새로고침하고 현재 질문에 답해주세요.',
        'APPROVAL_CHANGED': '승인된 F 마스크가 질문 생성 당시와 달라졌습니다. 현재 작업을 확인하세요.',
        'CLARIFICATION_PROVENANCE_MISMATCH': '질문과 현재 장면·지시·native 결과의 연결이 달라졌습니다.',
        'CLARIFICATION_ANSWER_UNSUPPORTED': '현재 질문의 방향 선택지에 맞춰 답해주세요.',
        'CLARIFICATION_RECOVERY_REQUIRED': '이전 답변 처리의 완료 기록을 확인할 수 없습니다. 자동 재실행하지 않았습니다.',
        'TRAJECTORY3_ADMISSION_FAILED': 'Trajectory3 입력·승인 세션·runtime 설정을 확인하세요. 기존 질문은 유지됩니다.',
        'TRAJECTORY3_NATIVE_FAILED': 'Trajectory3 native 실행이 실패했습니다. 기존 질문은 유지되며 명시적으로 다시 답할 수 있습니다.',
        'TRAJECTORY3_TIMEOUT': 'Trajectory3 실행 시간이 초과됐습니다. 기존 질문은 유지되며 자동 재시도하지 않았습니다.',
        'TRAJECTORY3_OUTPUT_INVALID': 'Trajectory3 결과가 경로 검증을 통과하지 못했습니다. 기존 질문과 실패 증거를 보존했습니다.',
    }
    def __init__(self, code, status_code=409):
        self.code = code
        super().__init__(self.MESSAGES[code], status_code)


def write_once(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False)


def resolution_supported(pending, direction):
    # The choices are backend-derived from the explicit native question. Actual
    # native questions need not contain the words "시작", "방향" or "어느 끝".
    offered = {answer_direction(value) for value in pending.choices}
    if offered:
        return direction in offered
    return any(t in pending.question for t in ('방향', '시작', '어느 끝', '어느끝'))


def failed_reply_reason(exc, runtime):
    if isinstance(exc, ClarificationError):
        return exc
    code = getattr(exc, 'code', None)
    if code in {'MODEL_NOT_CONFIGURED', 'NATIVE_INPUT_MISMATCH', 'NATIVE_MASK_NOT_APPROVED', 'NATIVE_BINDING_REQUIRED'}:
        return ClarificationError('TRAJECTORY3_ADMISSION_FAILED', 503)
    if code == 'MODEL_TIMEOUT' or isinstance(exc, TimeoutError):
        return ClarificationError('TRAJECTORY3_TIMEOUT', 503)
    capture = getattr(runtime, 'last_capture', None)
    if code == 'MODEL_PROCESS_FAILED' or (capture and capture.get('exit_code') != 0):
        return ClarificationError('TRAJECTORY3_NATIVE_FAILED', 503)
    if capture or code in {'MODEL_OUTPUT_INVALID', 'NATIVE_OUTPUT_HARD_INVALID', 'NATIVE_OUTPUT_MISSING', 'NATIVE_RESULT_INCOMPLETE'}:
        return ClarificationError('TRAJECTORY3_OUTPUT_INVALID', 422)
    return ClarificationError('TRAJECTORY3_ADMISSION_FAILED', 503)


def safe_question(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 2000:
        return None
    # Reject unsafe question fields rather than publishing paths/credentials or
    # replacing the native question with a fabricated one.
    if re.search(r'(?i)sk-|api[_ -]?key|token\s*[:=]|[a-z]:[\\/]|https?://|/(?:home|users|mnt|tmp|data)/|\\\\|<[^>]+>', value):
        return None
    return value.strip()


def extract(directory, files):
    for stage, name in (('planner', 'iteration_001/clarification.json'), ('refiner', 'refiner.json')):
        if name not in files:
            continue
        try:
            data = json.loads((directory / name).read_text(encoding='utf-8'))
            question = safe_question(data.get('clarification_question_ko'))
            if data.get('status') == 'needs_clarification' and question:
                return stage, question
        except (OSError, ValueError, AttributeError):
            continue
    return None


def choices(question):
    if re.search(r'세로|위쪽|아래쪽|위.*아래|수직', question):
        return ['위에서 아래로', '아래에서 위로']
    if re.search(r'가로|왼쪽|오른쪽|수평', question):
        return ['왼쪽에서 오른쪽으로', '오른쪽에서 왼쪽으로']
    return []


def answer_direction(answer):
    text = re.sub(r'\s+', '', answer.lower())
    if re.search(r"알아서|그쪽|아무|하지마|말고|않|금지|\?|할까|예시|설명|아니|반대로|취소|지말|마세요|don't|donot|never", text):
        return None
    matches = []
    for direction, pattern in (
        ('top_to_bottom', r'위(?:쪽)?(?:끝)?(?:에서|부터|→|->).{0,14}?아래|top(?:to|→|->|-)bottom'),
        ('bottom_to_top', r'아래(?:쪽)?(?:끝)?(?:에서|부터|→|->).{0,14}?위|bottom(?:to|→|->|-)top'),
        ('left_to_right', r'왼쪽(?:끝)?(?:에서|부터|→|->).{0,14}?오른쪽|left(?:to|→|->|-)right'),
        ('right_to_left', r'오른쪽(?:끝)?(?:에서|부터|→|->).{0,14}?왼쪽|right(?:to|→|->|-)left'),
    ):
        if re.search(pattern, text):
            matches.append(direction)
    return matches[0] if len(matches) == 1 else None


def resolved_instruction(direction):
    start, end = {
        'top_to_bottom': ('위쪽', '아래쪽'), 'bottom_to_top': ('아래쪽', '위쪽'),
        'left_to_right': ('왼쪽', '오른쪽'), 'right_to_left': ('오른쪽', '왼쪽'),
    }[direction]
    return f'표시된 이음선의 {start} 끝에서 시작하여 {end} 끝으로 용접한다.'


def message(pending):
    result = '추가 확인이 필요합니다.\n\n' + pending.question
    if pending.choices:
        result += '\n\n예: ' + ' / '.join(pending.choices)
    return result


def record_question(workflow, job, directory, proof):
    found = extract(directory, proof['files'])
    if not found:
        return False
    from backend.model_clients.native import read_json, sha256
    stage, question = found
    pending = TrajectoryClarification(id=uuid4(), question=question, stage=stage, choices=choices(question))
    original = job.instruction.text
    if job.clarification_history and job.instruction.parser == 'human-clarification':
        previous = workflow.storage.artifact_path('native_context', job.clarification_history[-1], '.clarification.json')
        original = read_json(previous)['original_instruction']
    record = dict(pending.model_dump(mode='json'), job_id=str(job.id), sample_id=job.scene.sample_id,
        mask_id=str(job.mask.id), approved_mask_hash=proof['mask_pixels_sha256'],
        mask_file_hash=proof['mask_sha256'], approval_timestamp=proof['approved_at'],
        original_instruction=original, input_instruction=job.instruction.model_dump(mode='json'),
        native_artifact_id=str(job.native_output.native_artifact_id), native_session_id=directory.name,
        native_proof_hash=sha256(workflow.storage.artifact_path('native_context', job.native_output.native_artifact_id, '.native-output.json')))
    path = workflow.storage.artifact_path('native_context', pending.id, '.clarification.json')
    with path.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, ensure_ascii=False)
    job.trajectory_clarification = pending
    job.planning_status = 'NEEDS_CLARIFICATION'
    return True


def verify_question(workflow, job):
    from backend.model_clients.native import read_json, sha256
    from backend.model_clients.contracts import ModelFault
    pending = job.trajectory_clarification
    if not pending:
        raise ClarificationError('CLARIFICATION_STALE')
    path = workflow.storage.artifact_path('native_context', pending.id, '.clarification.json')
    try:
        record = read_json(path)
        if (not job.mask or not job.mask.approved or job.mask.approved_at is None or record['mask_id'] != str(job.mask.id)
                or record['approval_timestamp'] != job.mask.approved_at.isoformat()
                or record['mask_file_hash'] != sha256(workflow.storage.artifact_path('masks', job.mask.id))):
            raise ClarificationError('APPROVAL_CHANGED')
        directory, proof = workflow.verify_native_output(job)
        expected = {k: record[k] for k in pending.model_dump()}
        if (pending.model_dump(mode='json') != expected or record['job_id'] != str(job.id)
                or record['sample_id'] != job.scene.sample_id or record['mask_id'] != str(job.mask.id)
                or record['approved_mask_hash'] != proof['mask_pixels_sha256']
                or record['mask_file_hash'] != proof['mask_sha256']
                or record['approval_timestamp'] != proof['approved_at']
                or record['input_instruction'] != job.instruction.model_dump(mode='json')
                or record['native_session_id'] != directory.name
                or record['native_artifact_id'] != str(job.native_output.native_artifact_id)
                or record['native_proof_hash'] != sha256(workflow.storage.artifact_path('native_context', job.native_output.native_artifact_id, '.native-output.json'))
                or extract(directory, proof['files']) != (pending.stage, pending.question)
                or workflow.storage.artifact_path('native_context', pending.id, '.clarification-answer.json').exists()):
            raise ValueError()
        return record
    except ClarificationError:
        raise
    except (OSError, KeyError, ValueError, TypeError, AttributeError, WorkflowError, ModelFault):
        raise ClarificationError('CLARIFICATION_PROVENANCE_MISMATCH') from None
