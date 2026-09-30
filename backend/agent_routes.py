from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.agent.config import AgentFault


class EmptyAction(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatRequest(EmptyAction):
    session_id: UUID
    job_id: UUID | None = None
    message: str = Field(min_length=1, max_length=2000)

    @field_validator("message")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Message is empty")
        return value.strip()


def agent_router(service, origins):
    router = APIRouter(prefix="/api/agent")
    allowed = {origin.strip() for origin in origins.split(",")}

    def check(request):
        if request.query_params or (request.headers.get("origin") and request.headers["origin"] not in allowed):
            raise AgentFault("invalid_request", "허용되지 않은 Agent 요청입니다.", 403)

    @router.get("/status")
    def status():
        return service.status()

    @router.post("/sessions", status_code=201)
    def create(request: Request, _body: EmptyAction | None = None):
        check(request)
        return {"session_id": service.sessions.create()}

    @router.get("/sessions/{session_id}/history")
    def history(session_id: UUID):
        return service.history(str(session_id))

    @router.post("/sessions/{session_id}/reset")
    async def reset(session_id: UUID, request: Request, _body: EmptyAction | None = None):
        check(request)
        await service.reset(str(session_id))
        return service.history(str(session_id))

    @router.post("/chat/stream")
    async def chat(body: ChatRequest, request: Request):
        check(request)
        queue = await service.begin(str(body.session_id), body.job_id, body.message)
        return StreamingResponse(service.stream(queue), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"})

    return router
