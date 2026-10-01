from backend.model_clients.config import ModelSettings
from backend.model_clients.rough import VlmTrajectoryClient
from backend.model_clients.runtime import ModelRuntime
from backend.model_clients.native import NativeRuntime, NativeSegmentClient, NativeRoughClient
from backend.model_clients.segmentation import RealVlmSegmentationClient
from backend.services.rough_path_client import DummyRoughPathClient
from backend.services.segmentation_client import DummySegmentationClient


def configured_clients():
    segment, rough = ModelSettings.from_env("segment"), ModelSettings.from_env("rough")
    def select(settings, dummy, native, experimental):
        if settings.backend == "dummy":
            return dummy()
        if settings.backend == "experimental":
            return experimental(ModelRuntime(settings))
        # `real` is a migration alias for native, NEVER image-only. Unknown modes fail closed.
        return native(NativeRuntime(settings))
    return (select(segment, DummySegmentationClient, NativeSegmentClient, RealVlmSegmentationClient),
            select(rough, DummyRoughPathClient, NativeRoughClient, VlmTrajectoryClient))


def client_status(client, dummy_type):
    runtime = getattr(client, "runtime", None)
    if runtime is not None:
        return runtime.status()
    return {"backend": "dummy" if isinstance(client, dummy_type) else "injected", "configured": True,
            "ready": True, "state": "READY", "code": None, "reference_mode": "dummy"}


def configured_rough3d_client():
    """Explicit opt-in factory; never replaces configured_clients()'s Rough2D baseline."""
    from backend.model_clients.native_rough3d import NativeRough3DClient
    from dataclasses import replace
    from backend.model_clients.config import ROOT
    from backend.model_clients.native import NATIVE_PYTHON
    settings = ModelSettings.from_env("rough3d")
    # Reuse the already audited owned Windows configuration when no explicit
    # rough3d override exists. No external config/source is generated or edited.
    candidate=ROOT/".cache/native-integration/configs/rough3d.windows.yaml"
    if settings.native_config is None and candidate.is_file():
        settings=replace(settings,backend="native",python=NATIVE_PYTHON,native_config=candidate,
                         native_binding=ROOT/".cache/native-integration/configs/binding.json",timeout=900)
    return NativeRough3DClient(NativeRuntime(settings))
