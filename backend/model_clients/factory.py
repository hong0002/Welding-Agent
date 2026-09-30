from backend.model_clients.config import ModelSettings
from backend.model_clients.rough import VlmTrajectoryClient
from backend.model_clients.runtime import ModelRuntime
from backend.model_clients.segmentation import RealVlmSegmentationClient
from backend.services.rough_path_client import DummyRoughPathClient
from backend.services.segmentation_client import DummySegmentationClient


def configured_clients():
    segment, rough = ModelSettings.from_env("segment"), ModelSettings.from_env("rough")
    # Unknown modes fail configuration checks; never silently fall back after a real-model error.
    return (DummySegmentationClient() if segment.backend == "dummy" else RealVlmSegmentationClient(ModelRuntime(segment)),
            DummyRoughPathClient() if rough.backend == "dummy" else VlmTrajectoryClient(ModelRuntime(rough)))


def client_status(client, dummy_type):
    runtime = getattr(client, "runtime", None)
    if runtime is not None:
        return runtime.status()
    return {"backend": "dummy" if isinstance(client, dummy_type) else "injected", "configured": True,
            "ready": True, "state": "READY", "code": None, "reference_mode": "dummy"}
