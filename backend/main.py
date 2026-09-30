import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, File, Form, Request, UploadFile
from pydantic import BaseModel, ConfigDict
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler

from backend.agent.config import AgentFault, AgentSettings
from backend.agent.service import AgentService
from backend.agent.welding_agent import AgentRunner
from backend.agent_routes import agent_router
from backend.model_clients.contracts import ModelFault
from backend.model_clients.factory import configured_clients

from backend.orchestrator.state_machine import WorkflowError
from backend.orchestrator.workflow import Workflow
from backend.schemas import AutomaticMaskRequest, ParseInstructionRequest, PlanRequest, WeldJob
from backend.services.components import DEFAULT_MIN_COMPONENT_AREA
from backend.services.storage import LocalStorage
from backend.services.simulator_client import LocalSimulatorClient, SimulatorClient

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class SimulatorAction(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MaskApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: UUID
    mask_id: UUID


def create_app(storage_dir: Path | None = None, *, workflow: Workflow | None = None,
               simulator: SimulatorClient | None = None, agent_settings: AgentSettings | None = None,
               agent_runner: AgentRunner | None = None) -> FastAPI:
    simulator = simulator or LocalSimulatorClient()

    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            await agent.close()
            simulator.close()

    app = FastAPI(title="Welding Agent · Preview API", version="0.1.0",
                  description="2D preview and an independent existing-sample simulator launcher. No robot execution.",
                  lifespan=lifespan)
    origins = os.getenv("WELD_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    app.add_middleware(
        CORSMiddleware, allow_origins=[value.strip() for value in origins.split(",") if value.strip()],
        allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
    )
    default_storage = Path(__file__).parent / "storage"
    segment_client, rough_client = configured_clients()
    workflow = workflow or Workflow(
        LocalStorage(storage_dir or Path(os.getenv("WELD_STORAGE_DIR", str(default_storage)))),
        min_component_area=int(os.getenv("WELD_MIN_COMPONENT_AREA", str(DEFAULT_MIN_COMPONENT_AREA))),
        segmentation=segment_client, rough=rough_client,
    )
    app.state.workflow = workflow
    app.state.simulator = simulator
    agent = AgentService(workflow, simulator, settings=agent_settings, runner=agent_runner)
    app.state.agent = agent
    app.include_router(agent_router(agent, origins))

    @app.exception_handler(AgentFault)
    async def agent_error_handler(_request, exc):
        return JSONResponse(status_code=exc.status, content={"code": exc.code, "detail": exc.message})

    @app.exception_handler(ModelFault)
    async def model_error_handler(_request, exc):
        return JSONResponse(status_code=exc.status, content={"code": exc.code, "detail": exc.message})

    @app.get("/api/models/status")
    def model_status():
        return workflow.model_status()

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request, exc):
        if request.url.path.startswith("/api/agent/"):
            return JSONResponse(status_code=422, content={"code": "invalid_request", "detail": "Agent 요청 형식이 올바르지 않습니다."})
        return await request_validation_exception_handler(request, exc)

    def check_simulator_action(request: Request):
        if request.query_params:
            raise WorkflowError("Simulator actions do not accept query parameters.", 400)
        origin = request.headers.get("origin")
        if origin and origin not in {value.strip() for value in origins.split(",")}:
            raise WorkflowError("Simulator action origin is not allowed.", 403)

    @app.get("/api/simulator/status")
    def simulator_status():
        return simulator.status()

    @app.get("/api/simulator/logs")
    def simulator_logs():
        return simulator.logs()

    @app.post("/api/simulator/start", status_code=202)
    def simulator_start(request: Request, _body: SimulatorAction | None = None):
        check_simulator_action(request)
        return simulator.start()

    @app.post("/api/simulator/run-sample", status_code=202)
    def simulator_run_sample(request: Request, _body: SimulatorAction | None = None):
        check_simulator_action(request)
        return simulator.run_sample()

    @app.post("/api/simulator/stop")
    def simulator_stop(request: Request, _body: SimulatorAction | None = None):
        check_simulator_action(request)
        return simulator.stop()

    @app.exception_handler(WorkflowError)
    async def workflow_error_handler(_request, exc: WorkflowError):
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    def read_upload(file: UploadFile) -> bytes:
        data = file.file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise WorkflowError("Maximum upload size is 20 MiB.", 413)
        if not data:
            raise WorkflowError("Uploaded file is empty.")
        return data

    def artifact(folder: str, artifact_id: UUID, suffix: str = ".png") -> FileResponse:
        path = workflow.storage.artifact_path(folder, artifact_id, suffix)
        if not path.is_file():
            raise WorkflowError("Artifact not found.", 404)
        return FileResponse(path, media_type="image/png")

    @app.get("/api/health")
    def health():
        mode = "dummy_preview" if all(item["backend"] == "dummy" for item in workflow.model_status().values()) else "mixed_preview"
        return {"status": "ok", "mode": mode, "trajectory_schema_version": 2,
                "robot_execution_enabled": False, "isaac": workflow.isaac.status()}

    @app.post("/api/scenes/upload", response_model=WeldJob, status_code=201)
    def upload_scene(file: Annotated[UploadFile, File()]):
        return workflow.upload_scene(read_upload(file))

    @app.get("/api/scenes/{scene_id}/image")
    def scene_image(scene_id: UUID):
        return artifact("scenes", scene_id)

    @app.post("/api/masks/manual", response_model=WeldJob)
    def manual_mask(
        job_id: Annotated[UUID, Form()], file: Annotated[UploadFile, File()],
        min_component_area: Annotated[int | None, Form(ge=1)] = None,
        edited_from_mask_id: Annotated[UUID | None, Form()] = None,
    ):
        with agent.manual_mutation(job_id):
            return workflow.set_mask(job_id, read_upload(file), min_component_area=min_component_area,
                                     edited_from_mask_id=edited_from_mask_id)

    @app.post("/api/masks/automatic", response_model=WeldJob)
    def automatic_mask(request: AutomaticMaskRequest):
        with agent.manual_mutation(request.job_id):
            return workflow.set_mask(request.job_id, min_component_area=request.min_component_area,
                                     instruction=request.instruction)

    @app.post("/api/masks/approve", response_model=WeldJob)
    def approve_mask(request: MaskApprovalRequest):
        with agent.manual_mutation(request.job_id):
            return workflow.approve_mask(request.job_id, request.mask_id)

    @app.get("/api/masks/{mask_id}/image")
    def mask_image(mask_id: UUID):
        return artifact("masks", mask_id)

    @app.get("/api/masks/{mask_id}/overlay")
    def mask_overlay(mask_id: UUID):
        return artifact("masks", mask_id, ".overlay.png")

    @app.post("/api/instructions/parse", response_model=WeldJob)
    def parse_instruction(request: ParseInstructionRequest):
        with agent.manual_mutation(request.job_id):
            return workflow.parse_instruction(request.job_id, request.instruction, request.region_selection)

    @app.post("/api/weld/plan", response_model=WeldJob)
    def plan(request: PlanRequest):
        with agent.manual_mutation(request.job_id):
            return workflow.plan(request.job_id)

    @app.get("/api/weld/{job_id}", response_model=WeldJob)
    def get_job(job_id: UUID):
        return workflow.get_job(job_id)

    @app.post("/api/weld/{job_id}/rough", response_model=WeldJob)
    def rough(job_id: UUID):
        with agent.manual_mutation(job_id):
            return workflow.generate_rough(job_id)

    @app.post("/api/weld/{job_id}/refine", response_model=WeldJob)
    def refine(job_id: UUID):
        with agent.manual_mutation(job_id):
            return workflow.refine(job_id)

    @app.post("/api/weld/{job_id}/validate", response_model=WeldJob)
    def validate(job_id: UUID):
        with agent.manual_mutation(job_id):
            return workflow.validate(job_id)

    return app


app = create_app()
