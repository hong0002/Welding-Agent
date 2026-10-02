"""Explicit Playwright-only factory. No real model or simulator can be constructed here."""
import os
from pathlib import Path
from PIL import Image, ImageDraw
from backend.agent.config import AgentSettings
from backend.main import create_app
from backend.orchestrator.workflow import Workflow
from backend.services.storage import LocalStorage
from backend.model_clients.contracts import Provenance
from tests.agent_fakes import FakeRunner, FakeSimulator
from tests.module_fakes import module_workflow


class OfflineSegmentation:
    def segment(self, image, *, instruction=""):
        mask = Image.new("L", image.size)
        draw = ImageDraw.Draw(mask)
        w, h = image.size
        for left, right, y in ((.18, .42, .3), (.6, .82, .7)):
            draw.rectangle((round(w * left), round(h * y - 12), round(w * right), round(h * y + 12)), fill=255)
        mask.info["model_provenance"] = Provenance(model_name="offline-e2e-fixture", model_version="1", latency_ms=0,
                                                   reference_mode="native" if "native-fixture" in instruction else "none", instruction=instruction)
        return mask


class OfflineCurrentPreview:
    """Playwright UI runtime only: cannot launch a process or prepare real assets."""
    entries = []
    def __init__(self, workflow):self.workflow=workflow
    def capabilities(self, *, job_id):
        job=self.workflow.storage.get_job(job_id)
        return dict(sample_id=job.scene.sample_id, family='B_PP' if job.scene.sample_id=='B_PP_03_0001' else 'B_PR',
            point_count=9, path_preview_ready=True, robot_preview_ready=job.scene.sample_id!='B_PP_03_0001',
            workpiece_preview_ready=False, fixture_ready=False, simulation_only=True,
            physical_robot_executable=False, validated_simulation=False, vla_orientation=False,
            configuration_codes=[], warnings=[])
    def status(self):
        return dict(configured=True, configuration_errors=[], configuration_codes=[],
            state='STOPPED', error=None, can_stop=False, pid=None, latest=None)
    def run(self, **kwargs):
        raise AssertionError('E2E preview actions require an explicit HTTP response fixture')
    def stop(self):pass
    def close(self):pass


def create_test_app():
    root = Path(os.environ["WELD_STORAGE_DIR"])
    replay = os.getenv('WELD_TEST_REAL_ARTIFACT_REPLAY') == '1'
    if replay:
        from tests.module_replay import replay_workflow
        from backend.model_clients.native import read_json
        workflow, _, _ = replay_workflow(root / 'artifact-replay')
        instructions = {
            'segment': read_json(workflow.segmentation.runtime.directory/'iteration_001/result.json')['instruction'],
            'rough': read_json(workflow.rough3d.runtime.directory/'iteration_001/plan.json')['raw_instruction_ko'],
        }
    else:
        from tests.native_stack_fakes import candidate_workflow
        scenario={'mode':'pass','vertical':False}
        def transform(directory):
            from tests.test_native_output_preview import far_mask,partial
            if scenario['mode']=='soft':far_mask(directory)
            elif scenario['mode']=='partial':partial(directory)
            elif scenario['mode']=='clarification':
                from tests.test_trajectory_clarification import clarification_output
                clarification_output(directory)
            elif scenario['mode']=='clarification_real':
                from tests.test_trajectory_clarification import clarification_output
                clarification_output(directory,question='화면에서 이음선이 세로로 보입니다. 이음선을 따라 위에서 아래로 용접할까요, 아래에서 위로 용접할까요?')
            elif scenario['mode']=='native_fail':
                from backend.model_clients.contracts import ModelFault
                raise ModelFault('MODEL_PROCESS_FAILED')
        workflow, _, native_calls = candidate_workflow(root / 'module-fixture',rough_output_transform=transform,vertical=lambda:scenario['vertical'])
    native_views=workflow.segmentation
    # Keep the original disconnected-region Dummy scenarios for arbitrary uploads.
    class Segmentation(OfflineSegmentation):
        runtime = native_views.runtime
        def segment_views(self, image, *, instruction=''):
            return native_views.segment_views(image, instruction=instruction)
    if not replay:workflow.segmentation = Segmentation()
    preview = OfflineCurrentPreview(workflow)
    app = create_app(workflow=workflow, simulator=FakeSimulator(), agent_runner=FakeRunner(),
                      current_vla_preview=preview, preview_runtime=preview,
                      agent_settings=AgentSettings(api_key="offline-test-placeholder", ready_timeout=1))
    if replay:
        @app.get('/api/test/replay-instructions')
        def replay_instructions():return instructions
    else:
        from pydantic import BaseModel
        from typing import Literal
        class FakeOutputMode(BaseModel):
            mode:Literal['pass','soft','partial','clarification','clarification_real','native_fail']
            vertical:bool=False
        @app.post('/api/test/native-output-mode')
        def native_output_mode(body:FakeOutputMode):
            scenario['mode']=body.mode
            scenario['vertical']=body.vertical
            return {'mode':scenario['mode'],'offline':True}
        @app.get('/api/test/native-call-counts')
        def native_call_counts():return {name:len(values) for name,values in native_calls.items()}
        @app.get('/api/test/yolo-replay')
        def yolo_display_replay():
            from tests.yolo_replay import SOURCE_JOB, install_display_replay
            if not SOURCE_JOB.is_file():
                return {'available':False}
            job=install_display_replay(workflow)
            return {'available':True,'job_id':str(job.id),'sample_id':job.scene.sample_id}
        @app.get('/api/test/bpp-preview-fixture')
        def bpp_preview_fixture():
            from tests.test_current_vla_preview import prepared
            from uuid import uuid4
            fixture_service, job, _, _ = prepared(root/'preview-fixtures'/str(uuid4()), 'B_PP_03_0001')
            from backend.schemas import Instruction, StructuredInstruction
            job.instruction=Instruction(text='위에서 아래로 용접한다.', structured=StructuredInstruction(
                direction='top_to_bottom', start_region=0, region_order=[0], skip_regions=[]))
            for view in job.scene.views.values():
                workflow.storage.save_image('scenes',view.image_id,fixture_service.storage.read_image('scenes',view.image_id))
                view.image_url=f'/api/scenes/{view.image_id}/image'
            workflow.storage.save_image('masks',job.mask.id,fixture_service.storage.read_image('masks',job.mask.id))
            job.mask.image_url=f'/api/masks/{job.mask.id}/image'
            job.scene.image_url=job.scene.views['F'].image_url
            workflow.storage.save_job(job)
            return job
    return app
