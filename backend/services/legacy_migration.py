"""Conservative v1 upgrade: keep inputs, invalidate the old potentially bridged polyline."""
from PIL import Image

from backend.orchestrator.state_machine import StateMachine
from backend.schemas import WeldJob, WorkflowState
from backend.services.components import detect_components


def upgrade_legacy_job(payload: dict, mask_image: Image.Image | None) -> WeldJob:
    payload = dict(payload)
    payload["schema_version"] = 2
    if payload.get("mask") is not None and mask_image is not None:
        # V1 did not filter noise; retain all original regions when upgrading its inputs.
        components = detect_components(mask_image, min_component_area=1)
        payload["mask"] = {
            **payload["mask"], "regions": [region.model_dump() for region in components.regions],
            "min_component_area": 1, "discarded_component_count": 0, "discarded_pixels": 0,
        }
    payload.update(instruction=None, rough_trajectory=None, final_trajectory=None, validation=None)
    job = WeldJob.model_validate(payload)
    state = WorkflowState.MASK_READY if job.mask else WorkflowState.SCENE_READY if job.scene else WorkflowState.EMPTY
    StateMachine.record(job, state, "schema_v2_upgrade; legacy_polyline_invalidated; reparse_instruction")
    return job
