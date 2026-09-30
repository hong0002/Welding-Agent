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


class OfflineSegmentation:
    def segment(self, image, *, instruction=""):
        mask = Image.new("L", image.size)
        draw = ImageDraw.Draw(mask)
        w, h = image.size
        for left, right, y in ((.18, .42, .3), (.6, .82, .7)):
            draw.rectangle((round(w * left), round(h * y - 12), round(w * right), round(h * y + 12)), fill=255)
        mask.info["model_provenance"] = Provenance(model_name="offline-e2e-fixture", model_version="1", latency_ms=0,
                                                   reference_mode="none", instruction=instruction)
        return mask


def create_test_app():
    workflow = Workflow(LocalStorage(Path(os.environ["WELD_STORAGE_DIR"])), segmentation=OfflineSegmentation())
    return create_app(workflow=workflow, simulator=FakeSimulator(), agent_runner=FakeRunner(),
                      agent_settings=AgentSettings(api_key="offline-test-placeholder", ready_timeout=1))
