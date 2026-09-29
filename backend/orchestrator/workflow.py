from uuid import UUID, uuid4

from backend.orchestrator.instruction_parser import DummyInstructionParser, InstructionParser
from backend.orchestrator.region_selection import resolve_regions
from backend.orchestrator.state_machine import StateMachine, WorkflowError
from backend.schemas import Instruction, Mask, RegionSelection, Scene, StateEvent, WeldJob, WorkflowState
from backend.services.components import DEFAULT_MIN_COMPONENT_AREA, detect_components
from backend.services.isaac_client import DisabledIsaacClient, IsaacClient
from backend.services.mask_service import create_mask_overlay, decode_image, validate_binary_mask
from backend.services.rough_path_client import DummyRoughPathClient, RoughPathClient
from backend.services.segmentation_client import DummySegmentationClient, SegmentationClient
from backend.services.storage import LocalStorage
from backend.services.validation import DummyTrajectoryValidator, TrajectoryValidator
from backend.services.vla_client import DummyVLAClient, VLAClient


class Workflow:
    def __init__(
        self, storage: LocalStorage, *, parser: InstructionParser | None = None,
        segmentation: SegmentationClient | None = None, rough: RoughPathClient | None = None,
        vla: VLAClient | None = None, validator: TrajectoryValidator | None = None,
        isaac: IsaacClient | None = None,
        min_component_area: int = DEFAULT_MIN_COMPONENT_AREA,
    ):
        if min_component_area < 1:
            raise ValueError("min_component_area must be at least 1.")
        self.min_component_area = min_component_area
        self.storage = storage
        self.parser = parser or DummyInstructionParser()
        self.segmentation = segmentation or DummySegmentationClient()
        self.rough = rough or DummyRoughPathClient()
        self.vla = vla or DummyVLAClient()
        self.validator = validator or DummyTrajectoryValidator()
        self.isaac = isaac or DisabledIsaacClient()

    def upload_scene(self, data: bytes) -> WeldJob:
        image = decode_image(data)
        scene_id = uuid4()
        job = WeldJob(id=uuid4(), history=[StateEvent(state=WorkflowState.EMPTY, reason="created")])
        job.scene = Scene(id=scene_id, width=image.width, height=image.height, image_url=f"/api/scenes/{scene_id}/image")
        with self.storage.lock:
            self.storage.save_image("scenes", scene_id, image)
            StateMachine.advance(job, WorkflowState.SCENE_READY)
            self.storage.save_job(job)
        return job

    def set_mask(self, job_id: UUID, data: bytes | None = None, *, min_component_area: int | None = None) -> WeldJob:
        with self.storage.lock:
            job = self.storage.get_job(job_id)
            StateMachine.require(job, *StateMachine.sequence[1:])
            if job.scene is None:
                raise WorkflowError("A scene is required.", 409)
            image = self.storage.read_image("scenes", job.scene.id)
            mask = decode_image(data, mask=True) if data is not None else self.segmentation.segment(image)
            selected = validate_binary_mask(mask, image.size)
            threshold = self.min_component_area if min_component_area is None else min_component_area
            if threshold < 1:
                raise WorkflowError("min_component_area must be at least 1.")
            components = detect_components(mask, threshold)
            if not components.regions:
                raise WorkflowError(f"No welding regions remain after filtering components smaller than {threshold} pixels.")
            overlay = create_mask_overlay(image, mask)
            mask_id = uuid4()
            self.storage.save_image("masks", mask_id, mask)
            self.storage.save_image("masks", mask_id, overlay, ".overlay.png")
            job.mask = Mask(
                id=mask_id, scene_id=job.scene.id, width=mask.width, height=mask.height,
                mask_source="manual" if data is not None else "automatic",
                image_url=f"/api/masks/{mask_id}/image", overlay_url=f"/api/masks/{mask_id}/overlay",
                selected_pixels=selected,
                regions=components.regions, min_component_area=threshold,
                discarded_component_count=components.discarded_component_count,
                discarded_pixels=components.discarded_pixels,
            )
            StateMachine.replace_mask(job)
            self._save(job)
            return job

    def parse_instruction(self, job_id: UUID, text: str, selection: RegionSelection | None = None) -> WeldJob:
        with self.storage.lock:
            job = self.storage.get_job(job_id)
            StateMachine.require(job, *StateMachine.sequence[2:])
            if job.mask is None:
                raise WorkflowError("A confirmed mask is required.", 409)
            structured = resolve_regions(self.parser.parse(text), job.mask.regions, selection)
            job.instruction = Instruction(text=text.strip(), structured=structured, parser=type(self.parser).__name__)
            StateMachine.replace_instruction(job)
            self._save(job)
            return job

    def generate_rough(self, job_id: UUID) -> WeldJob:
        with self.storage.lock:
            job = self.storage.get_job(job_id)
            StateMachine.require(job, WorkflowState.INSTRUCTION_READY)
            image, mask, components = self._conditioning(job)
            if job.instruction is None:
                raise WorkflowError("A parsed instruction is required.", 409)
            rough = self.rough.predict(image, mask, job.instruction.structured, components)
            # Reject malformed adapter output before passing it to a refinement service.
            report = self.validator.validate(
                rough, job.scene, components=components,
                expected_segments=list(enumerate(job.instruction.structured.region_order)),
            )
            if not report.valid:
                raise WorkflowError("Rough preview rejected: " + "; ".join(report.errors))
            job.rough_trajectory = rough
            StateMachine.advance(job, WorkflowState.ROUGH_PATH_READY)
            self._save(job)
            return job

    def refine(self, job_id: UUID) -> WeldJob:
        with self.storage.lock:
            job = self.storage.get_job(job_id)
            StateMachine.require(job, WorkflowState.ROUGH_PATH_READY)
            image, mask, _components = self._conditioning(job)
            if job.instruction is None or job.rough_trajectory is None:
                raise WorkflowError("Rough trajectory and instruction are required.", 409)
            final = self.vla.refine(image, mask, job.rough_trajectory, job.instruction.text, job.instruction.structured)
            # Point schema already rejects NaN/Inf. Geometry acceptance is the next explicit step.
            job.final_trajectory = final
            StateMachine.advance(job, WorkflowState.VLA_REFINED)
            self._save(job)
            return job

    def validate(self, job_id: UUID) -> WeldJob:
        with self.storage.lock:
            job = self.storage.get_job(job_id)
            StateMachine.require(job, WorkflowState.VLA_REFINED)
            if job.scene is None or job.final_trajectory is None or job.rough_trajectory is None:
                raise WorkflowError("Final preview, rough preview, and scene are required.", 409)
            _image, _mask, components = self._conditioning(job)
            job.validation = self.validator.validate(
                job.final_trajectory, job.scene, components=components,
                expected_segments=[(segment.segment_id, segment.region_id) for segment in job.rough_trajectory.segments],
            )
            if job.validation.valid:
                StateMachine.advance(job, WorkflowState.VALIDATED)
            self._save(job)
            if not job.validation.valid:
                raise WorkflowError("Final preview rejected: " + "; ".join(job.validation.errors))
            return job

    def plan(self, job_id: UUID) -> WeldJob:
        # RLock prevents edits interleaving with a plan in this single-process MVP.
        with self.storage.lock:
            job = self.storage.get_job(job_id)
            StateMachine.require(job, *StateMachine.sequence[3:])
            if job.state == WorkflowState.INSTRUCTION_READY:
                job = self.generate_rough(job_id)
            if job.state == WorkflowState.ROUGH_PATH_READY:
                job = self.refine(job_id)
            if job.state == WorkflowState.VLA_REFINED:
                job = self.validate(job_id)
            return job

    def get_job(self, job_id: UUID) -> WeldJob:
        with self.storage.lock:
            return self.storage.get_job(job_id)

    def _conditioning(self, job: WeldJob):
        if job.scene is None or job.mask is None:
            raise WorkflowError("Scene and confirmed mask are required.", 409)
        image = self.storage.read_image("scenes", job.scene.id)
        mask = self.storage.read_image("masks", job.mask.id)
        return image, mask, detect_components(mask, job.mask.min_component_area)

    def _save(self, job: WeldJob) -> None:
        self.storage.save_trajectories(job)
        self.storage.save_job(job)
