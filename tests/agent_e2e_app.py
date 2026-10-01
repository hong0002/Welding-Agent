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
        workflow, _ = module_workflow(root / 'module-fixture')
    # Keep the original disconnected-region Dummy scenarios for arbitrary uploads.
    class Segmentation(OfflineSegmentation):
        def segment_views(self, image, *, instruction=''):
            from tests.module_fakes import OfflineViews
            return OfflineViews().segment_views(image, instruction=instruction)
    if not replay:workflow.segmentation = Segmentation()
    app = create_app(workflow=workflow, simulator=FakeSimulator(), agent_runner=FakeRunner(),
                      agent_settings=AgentSettings(api_key="offline-test-placeholder", ready_timeout=1))
    if replay:
        @app.get('/api/test/replay-instructions')
        def replay_instructions():return instructions
    return app
