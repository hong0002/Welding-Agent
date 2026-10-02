import asyncio
import importlib.util
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

DEFAULT_MODEL = "gpt-6-luna"
ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"


@dataclass(frozen=True)
class AgentSettings:
    enabled: bool = True
    api_key: str = field(default="", repr=False)
    model: str = DEFAULT_MODEL
    max_turns: int = 8
    run_timeout: float = 420
    ready_timeout: float = 185
    reasoning_effort: str = "low"

    @classmethod
    def from_env(cls, env_file: Path = ROOT_ENV):
        # The secret is read only from the project's .env, never from browser input.
        values = dotenv_values(env_file, interpolate=False) if env_file.is_file() else {}
        def setting(name, default):
            return os.environ.get(name, values.get(name) or default)
        try:
            turns = max(1, min(20, int(setting("WELD_AGENT_MAX_TURNS", "8"))))
        except ValueError:
            turns = 8
        model = setting("OPENAI_MODEL", DEFAULT_MODEL).strip()
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:-]{0,100}", model):
            model = DEFAULT_MODEL
        effort = setting("WELD_AGENT_REASONING_EFFORT", "low").strip().lower()
        # "light" is a human label; the Responses API uses "low".
        if effort == "light":
            effort = "low"
        if effort not in {"none", "minimal", "low", "medium", "high", "xhigh", "max"}:
            effort = "low"
        try:
            run_timeout = max(30, min(1200, float(setting("WELD_AGENT_RUN_TIMEOUT", "420"))))
        except ValueError:
            run_timeout = 420
        return cls(enabled=setting("WELD_AGENT_ENABLED", "true").lower() == "true", run_timeout=run_timeout,
                   api_key=(values.get("OPENAI_API_KEY") or "").strip(), model=model, max_turns=turns,
                   reasoning_effort=effort)

    def status(self):
        sdk = importlib.util.find_spec("agents") is not None
        state = "DISABLED" if not self.enabled else "NOT CONFIGURED" if not self.api_key or not sdk else "READY"
        return {"enabled": self.enabled, "api_key_configured": bool(self.api_key), "model": self.model,
                "sdk_available": sdk, "state": state}


class AgentFault(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def redact(text: str, secret: str = "") -> str:
    if secret:
        text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[REDACTED]", text)
    text = re.sub(r"(?i)(?:[a-z]:[\\/]|/(?:home|users|tmp|var|mnt)/)[^\s\"'<>]+", "[LOCAL_PATH]", text)
    return text


def public_error(exc: Exception) -> AgentFault:
    from backend.orchestrator.state_machine import WorkflowError
    from backend.model_clients.contracts import ModelFault
    from backend.model_clients.guided_vla import GuidedVLAError
    from backend.orchestrator.clarification import ClarificationError
    if isinstance(exc, ClarificationError):
        return AgentFault(exc.code, str(exc), exc.status_code)
    if isinstance(exc, GuidedVLAError):
        return AgentFault(exc.code, "Guided VLA 입력 또는 서버 설정을 확인하세요. 자동 재시도하지 않았습니다.", 503)
    if isinstance(exc, ModelFault):
        return AgentFault(exc.code, exc.message, exc.status)
    if isinstance(exc, AgentFault):
        return exc
    if isinstance(exc, WorkflowError):
        if exc.status_code == 409:
            return AgentFault("workflow_invalid_state", "작업 순서를 확인하세요. 먼저 마스크와 지시를 준비해야 합니다.", 409)
        return AgentFault("tool_validation_error", "영역 선택 또는 경로 검증에 실패했습니다. 현재 영역과 작업 지시를 확인하세요.")
    name = type(exc).__name__
    if name == "AuthenticationError":
        return AgentFault("authentication_failed", "OpenAI API 인증에 실패했습니다. 설정을 확인해주세요.", 503)
    if name in ("NotFoundError", "BadRequestError", "PermissionDeniedError"):
        return AgentFault("model_unavailable", "OpenAI 모델 또는 요청 설정을 사용할 수 없습니다. 모델 접근 권한과 설정을 확인해주세요.", 503)
    if name == "RateLimitError":
        return AgentFault("rate_limit", "OpenAI 사용 한도에 도달했습니다. 잠시 후 다시 시도하세요.", 429)
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)) or name in ("APITimeoutError", "APIConnectionError"):
        return AgentFault("network_timeout", "응답 시간이 초과되었거나 연결에 실패했습니다. 현재 작업 상태를 확인한 후 다시 시도하세요.", 503)
    if name == "MaxTurnsExceeded":
        return AgentFault("max_turns", "Agent의 최대 작업 횟수에 도달했습니다. 현재 결과를 확인하고 요청을 구체화해주세요.")
    if name in ("ValidationError", "ModelBehaviorError"):
        return AgentFault("tool_validation_error", "Agent 도구 입력 형식이 올바르지 않아 요청을 중단했습니다.")
    return AgentFault("agent_error", "Agent 요청을 완료하지 못했습니다. 수동 조작으로 현재 상태를 확인할 수 있습니다.", 503)
