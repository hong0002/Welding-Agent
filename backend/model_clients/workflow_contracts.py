"""Injectable module boundaries, independent from image-pixel Dummy VLA."""
from typing import Protocol, TYPE_CHECKING
from PIL import Image
from backend.schemas import StructuredInstruction, VLAResultSummary, WeldJob
from backend.services.components import MaskComponents
from backend.services.storage import LocalStorage

if TYPE_CHECKING:
    from backend.model_clients.native_rough3d import NativeRough3DResult


class Rough3DClient(Protocol):
    def predict(self, image: Image.Image, mask: Image.Image, instruction: StructuredInstruction,
                components: MaskComponents, *, language: str = '') -> 'NativeRough3DResult': ...


class GuidedWorkflowClient(Protocol):
    def status(self) -> dict: ...
    def check_server(self) -> dict: ...
    def run(self, storage: LocalStorage, job: WeldJob) -> VLAResultSummary: ...
