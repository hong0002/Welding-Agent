import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, File, Form, Request, UploadFile
from pydantic import BaseModel, ConfigDict, model_validator
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler

from backend.agent.config import AgentFault, AgentSettings
from backend.agent.service import AgentService
from backend.agent.welding_agent import AgentRunner
from backend.agent_routes import agent_router
from backend.model_clients.contracts import ModelFault
from backend.model_clients.factory import configured_clients,configured_rough3d_client
from backend.model_clients.guided_workflow import WorkflowGuidedVLAClient
from backend.model_clients.guided_vla import GuidedVLAError

from backend.orchestrator.state_machine import WorkflowError
from backend.orchestrator.workflow import Workflow
from backend.schemas import AutomaticMaskRequest, ParseInstructionRequest, PlanRequest, WeldJob,SampleSceneRequest,RoughModeRequest
from backend.services.components import DEFAULT_MIN_COMPONENT_AREA
from backend.services.storage import LocalStorage
from backend.services.simulator_client import LocalSimulatorClient, SimulatorClient
from backend.services.simulator_prediction_package import CurrentVLASimulatorService
from backend.services.current_vla_preview import CurrentVLAPreviewService
from backend.services.current_preview_runtime import CurrentPreviewRuntime
from backend.services.current_preview_config import CurrentPreviewError
from backend.orchestrator.clarification import ClarificationError

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class UTF8JSONResponse(JSONResponse):
    # Explicit charset avoids legacy Windows HTTP clients decoding JSON as Latin-1.
    media_type = 'application/json; charset=utf-8'


class SimulatorAction(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CurrentVLAPredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_id: UUID


class CurrentPreviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    job_id: UUID | None = None
    artifact_id: UUID | None = None

    @model_validator(mode='after')
    def one_identity(self):
        if (self.job_id is None) == (self.artifact_id is None):
            raise ValueError('Supply exactly one job_id or artifact_id')
        return self


class MaskApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: UUID
    mask_id: UUID
    view_id: str | None = None


def create_app(storage_dir: Path | None = None, *, workflow: Workflow | None = None,
               simulator: SimulatorClient | None = None, agent_settings: AgentSettings | None = None,
               agent_runner: AgentRunner | None = None, current_vla_simulator=None,
               current_vla_preview=None, preview_runtime=None) -> FastAPI:
    simulator = simulator or LocalSimulatorClient()
    current_vla_simulator = current_vla_simulator or CurrentVLASimulatorService(simulator)

    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            await agent.close()
            simulator.close()
            preview_runtime.close()

    app = FastAPI(title="Welding Agent · Preview API", version="0.1.0",
                  description="2D preview and an independent existing-sample simulator launcher. No robot execution.",
                  lifespan=lifespan, default_response_class=UTF8JSONResponse)
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
        rough3d=configured_rough3d_client(),guided_vla=WorkflowGuidedVLAClient(),
    )
    app.state.workflow = workflow
    app.state.simulator = simulator
    app.state.current_vla_simulator = current_vla_simulator
    if current_vla_preview is None:
        from dataclasses import replace
        from backend.services.simulator_client import SimulatorConfig
        from backend.services.simulator2_client import backend_selection, DatasetSimulatorV2Client
        preview_backend, preview_root = backend_selection()
        preview_config = getattr(simulator, 'config', None) or SimulatorConfig.from_env()
        if preview_backend == 'dataset_v2':
            preview_config = replace(preview_config, root=preview_root)
        preview_runtime = preview_runtime or CurrentPreviewRuntime(preview_config, backend=preview_backend)
        current_vla_preview = (DatasetSimulatorV2Client(workflow.storage,preview_runtime,root=preview_root)
            if preview_backend=='dataset_v2' else CurrentVLAPreviewService(workflow.storage, preview_runtime))
    else:
        preview_runtime = preview_runtime or current_vla_preview.runtime
    app.state.current_vla_preview = current_vla_preview
    app.state.preview_runtime = preview_runtime
    agent = AgentService(workflow, simulator, settings=agent_settings, runner=agent_runner)
    app.state.agent = agent
    # Agent proxy sessions support both fixed dev origins; explicit policy wins.
    # Keep the independent simulator action/CORS configuration unchanged.
    app.include_router(agent_router(agent, os.getenv('WELD_CORS_ORIGINS')))

    @app.exception_handler(AgentFault)
    async def agent_error_handler(_request, exc):
        return JSONResponse(status_code=exc.status, content={"code": exc.code, "detail": exc.message})

    @app.exception_handler(ModelFault)
    async def model_error_handler(_request, exc):
        return JSONResponse(status_code=exc.status, content={"code": exc.code, "detail": exc.message})

    @app.exception_handler(GuidedVLAError)
    async def guided_error_handler(_request,exc):
        messages={'GUIDED_VLA_TOKEN_REQUIRED':'Backend VLA API token 설정이 필요합니다.',
                  'GUIDED_VLA_SERVER_UNAVAILABLE':'Guided VLA 서버 readiness를 확인할 수 없습니다.',
                  'GUIDED_VLA_GUIDANCE_INVALID':'현재 승인 F mask와 Rough3D guidance를 확인하세요.',
                  'GUIDED_VLA_ATTEMPT_CHANGED':'입력 artifact가 변경됐습니다. 현재 작업을 다시 확인하세요.'}
        return JSONResponse(status_code=503,content={'code':exc.code,'detail':messages.get(exc.code,'Guided VLA 요청을 완료하지 못했습니다. 자동 재시도하지 않았습니다.')})

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
        return simulator_snapshot()

    def simulator_snapshot():
        status = simulator.status()
        if 'existing_replay' not in status:
            errors = status.get('configuration_errors', []) + status.get('sample_configuration_errors', [])
            status['existing_replay'] = dict(configured=bool(status.get('configured')) and not errors, errors=errors)
        current = preview_runtime.status()
        status['current_preview'] = current
        status['backend'] = current.get('backend', 'legacy')
        status['simulator_version'] = current.get('simulator_version', 'legacy')
        if current['can_stop']:
            status.update(can_start=False, can_run_sample=False, can_stop=True)
        return status

    @app.get("/api/simulator/logs")
    def simulator_logs():
        output = simulator.logs()
        output['entries'] = output['entries'] + list(getattr(preview_runtime, 'entries', []))
        return output

    def preview_action(request, body, kind):
        check_simulator_action(request)
        if body.job_id:
            with agent.manual_mutation(body.job_id):
                current_vla_preview.run(job_id=body.job_id, kind=kind)
        else:
            proof = workflow.storage.artifact_path('native_context', body.artifact_id, '.vla.json')
            if proof.is_file():
                import json
                try:
                    jid = UUID(json.loads(proof.read_text(encoding='utf-8'))['job_id'])
                except (OSError, ValueError, KeyError, TypeError, AttributeError):
                    raise CurrentPreviewError('CURRENT_PREVIEW_ARTIFACT_INVALID', 'Current VLA artifact has an invalid job binding.', 409) from None
                with agent.manual_mutation(jid):
                    current_vla_preview.run(job_id=jid, artifact_id=body.artifact_id, kind=kind)
            else:
                with workflow.storage.lock:
                    current_vla_preview.run(artifact_id=body.artifact_id, kind=kind)
        return simulator_snapshot()

    @app.post('/api/simulator/preview-current-vla', status_code=202)
    def preview_current_vla(request: Request, body: CurrentPreviewRequest):
        return preview_action(request, body, 'robot')

    @app.post('/api/simulator/preview-current-vla/path', status_code=202)
    def preview_current_vla_path(request: Request, body: CurrentPreviewRequest):
        return preview_action(request, body, 'path')

    @app.get('/api/simulator/current-vla/capabilities')
    def current_preview_capabilities(job_id: UUID):
        with workflow.storage.lock:
            return current_vla_preview.capabilities(job_id=job_id)

    @app.post('/api/simulator/current-vla/preview-preflight')
    def current_preview_offline_preflight(request: Request, body: CurrentPreviewRequest):
        """Explicit native offline robot preflight; no GUI, queue or model dispatch."""
        check_simulator_action(request)
        if getattr(current_vla_preview,'backend',None)!='dataset_v2' or not body.job_id:
            raise CurrentPreviewError('SIMULATOR2_SAMPLE_UNSUPPORTED','Offline robot preflight requires dataset_v2 and a current job UUID.',409)
        with agent.manual_mutation(body.job_id):
            current_vla_preview.prepare(job_id=body.job_id,artifact_id=body.artifact_id,kind='robot')
            return current_vla_preview.capabilities(job_id=body.job_id)

    @app.post("/api/simulator/start", status_code=202)
    def simulator_start(request: Request, _body: SimulatorAction | None = None):
        check_simulator_action(request)
        return simulator.start()

    @app.post("/api/simulator/run-sample", status_code=202)
    def simulator_run_sample(request: Request, _body: SimulatorAction | None = None):
        check_simulator_action(request)
        return simulator.run_sample()

    @app.post("/api/simulator/current-vla/preflight")
    def simulator_current_preflight(request: Request, body: CurrentVLAPredictionRequest):
        check_simulator_action(request)
        with workflow.storage.lock:
            return current_vla_simulator.preflight(body.artifact_id)

    @app.post("/api/simulator/run-current-vla", status_code=202)
    def simulator_run_current(request: Request, body: CurrentVLAPredictionRequest):
        check_simulator_action(request)
        with workflow.storage.lock:
            return current_vla_simulator.run_current_vla_prediction(body.artifact_id)

    @app.post("/api/simulator/stop")
    def simulator_stop(request: Request, _body: SimulatorAction | None = None):
        check_simulator_action(request)
        preview_runtime.stop()
        simulator.stop()
        return simulator_snapshot()

    @app.exception_handler(WorkflowError)
    async def workflow_error_handler(_request, exc: WorkflowError):
        content = {"detail": str(exc)}
        if isinstance(exc, (CurrentPreviewError, ClarificationError)):
            content['code'] = exc.code
        return UTF8JSONResponse(status_code=exc.status_code, content=content)

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
        statuses = workflow.model_status()
        # This legacy health label describes the default image-pixel pipeline.
        # Optional Guided VLA availability is reported independently by model status.
        mode = "dummy_preview" if all(statuses[stage]["backend"] == "dummy" for stage in ("segment", "rough")) else "mixed_preview"
        return {"status": "ok", "mode": mode, "trajectory_schema_version": 2,
                "robot_execution_enabled": False, "isaac": workflow.isaac.status()}

    @app.post("/api/scenes/upload", response_model=WeldJob, status_code=201)
    def upload_scene(file: Annotated[UploadFile, File()]):
        return workflow.upload_scene(read_upload(file),file.filename)

    @app.post('/api/scenes/sample',response_model=WeldJob,status_code=201)
    def sample_scene(body:SampleSceneRequest):
        return workflow.load_sample(body.sample_id)

    @app.get("/api/scenes/{scene_id}/image")
    def scene_image(scene_id: UUID):
        return artifact("scenes", scene_id)

    @app.post("/api/masks/manual", response_model=WeldJob)
    def manual_mask(
        job_id: Annotated[UUID, Form()], file: Annotated[UploadFile, File()],
        min_component_area: Annotated[int | None, Form(ge=1)] = None,
        edited_from_mask_id: Annotated[UUID | None, Form()] = None,
        view_id: Annotated[str | None, Form()] = None,
    ):
        with agent.manual_mutation(job_id):
            return workflow.set_mask(job_id, read_upload(file), min_component_area=min_component_area,
                                     edited_from_mask_id=edited_from_mask_id,view_id=view_id)

    @app.post("/api/masks/automatic", response_model=WeldJob)
    def automatic_mask(request: AutomaticMaskRequest):
        with agent.manual_mutation(request.job_id):
            return workflow.set_mask(request.job_id, min_component_area=request.min_component_area,
                                     instruction=request.instruction)

    @app.post("/api/masks/approve", response_model=WeldJob)
    def approve_mask(request: MaskApprovalRequest):
        with agent.manual_mutation(request.job_id):
            return workflow.approve_mask(request.job_id, request.mask_id,request.view_id)

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

    @app.post('/api/weld/rough-mode',response_model=WeldJob)
    def rough_mode(body:RoughModeRequest):
        with agent.manual_mutation(body.job_id):return workflow.select_rough_mode(body.job_id,body.mode)

    @app.post('/api/weld/{job_id}/guided-vla',response_model=WeldJob)
    def guided_vla(job_id:UUID,_body:SimulatorAction):
        with agent.manual_mutation(job_id):return workflow.run_guided_vla(job_id)

    @app.get('/api/weld/{job_id}/rough3d/reference-preview')
    def rough3d_reference_preview(job_id:UUID):
        return FileResponse(workflow.rough3d_reference_preview(job_id),media_type='image/jpeg')

    @app.get('/api/weld/{job_id}/native-output/image/{kind}')
    def native_output_image(job_id:UUID,kind:str):
        return FileResponse(workflow.native_output_image(job_id,kind),media_type='image/jpeg')

    @app.post('/api/models/guided-vla/check')
    def check_guided(_body:SimulatorAction):
        if workflow.guided_vla is None:raise WorkflowError('Guided VLA adapter가 없습니다.',503)
        return workflow.guided_vla.check_server()

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
