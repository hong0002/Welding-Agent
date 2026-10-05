from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from backend.model_clients.contracts import ModelArtifact


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")


RegionId = Annotated[int, Field(ge=0, strict=True)]


class Point2D(Schema):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    x: float
    y: float


class BoundingBox(Schema):
    x_min: int
    y_min: int
    x_max: int
    y_max: int


class MaskRegion(Schema):
    region_id: RegionId
    pixel_area: int = Field(gt=0)
    bounding_box: BoundingBox
    centroid: Point2D


class WorkflowState(str, Enum):
    EMPTY = "EMPTY"
    SCENE_READY = "SCENE_READY"
    MASK_READY = "MASK_READY"
    INSTRUCTION_READY = "INSTRUCTION_READY"
    ROUGH_PATH_READY = "ROUGH_PATH_READY"
    VLA_REFINED = "VLA_REFINED"
    VALIDATED = "VALIDATED"
    VLA_READY = "VLA_READY"


class Scene(Schema):
    id: UUID
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    image_url: str
    color_mode: Literal["RGB"] = "RGB"
    artifact: ModelArtifact | None = None
    sample_id: str | None = None
    split: Literal["train", "val"] | None = None
    primary_view: str | None = None
    views: dict[str, "SceneView"] = Field(default_factory=dict)


class Mask(Schema):
    id: UUID
    scene_id: UUID
    width: int
    height: int
    mask_source: Literal["manual", "automatic", "vlm_segment", "manual_edited", "ai_refined"]
    artifact: ModelArtifact | None = None
    edited_from_mask_id: UUID | None = None
    approved: bool = True  # Legacy/dummy masks keep their previous confirmation behavior.
    approved_at: datetime | None = None
    image_url: str
    overlay_url: str
    selected_pixels: int = Field(gt=0)
    regions: list[MaskRegion]
    min_component_area: int = Field(ge=1)
    discarded_component_count: int = Field(default=0, ge=0)
    discarded_pixels: int = Field(default=0, ge=0)
    connectivity: Literal[8] = 8
    encoding: Literal["grayscale_png_0_255"] = "grayscale_png_0_255"
    role: Literal["2d_visual_conditioning"] = "2d_visual_conditioning"
    view_id: str | None = None


class SceneView(Schema):
    view_id: Literal["B", "F", "L", "R", "S1", "S2", "S3", "S4", "T"]
    image_id: UUID
    image_url: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    image_sha256: str
    mask: Mask | None = None


Scene.model_rebuild()


class Rough3DArtifact(Schema):
    reference_preview_url: str | None = None
    artifact_id: UUID
    native_session_id: str
    source_mask_id: UUID
    source_mask_sha256: str
    approved_at: datetime
    image_guidance_view: Literal["F"] = "F"
    image_guidance_point_count: int
    reference_sample_id: str
    reference_coordinate_frame: Literal["retrieved_teaching_start_relative"]
    reference_point_count: int
    reference_in_request: Literal[False] = False
    is_robot_executable: Literal[False] = False
    artifacts: dict[str, bool] = Field(default_factory=dict)


class VLAResultSummary(Schema):
    retrieval_mode: Literal['segment2_adapter','local','none'] | None = None
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    artifact_id: UUID
    attempt_id: UUID
    sample_id: str
    split: Literal["train", "val"]
    model: str | None = None
    point_count: Literal[9,33] = 9
    coordinate_frame: str
    units: Literal["mm"] = "mm"
    ade_mm: float
    fde_mm: float
    mask_views: list[str]
    simulation_only: Literal[True] = True
    physical_robot_executable: Literal[False] = False
    is_robot_executable: Literal[False] = False
    simulator_ready: Literal[False] = False
    source: Literal['guided_vla','vlm_final_gpt'] = 'guided_vla'
    provider: Literal['guided_vla','gpt'] = 'guided_vla'
    raw_output_ref: str | None = None
    validation_status: Literal['PASS'] = 'PASS'


class FinalPredictionDisplay(Schema):
    mask_views: list[Literal['F','R','S4']] = Field(default_factory=list)
    mask_provenance: dict[str,list[str]] = Field(default_factory=dict)
    retrieval_mode: Literal['segment2_adapter','local','none'] | None = None
    artifact_id: UUID
    attempt_id: UUID
    source: Literal['vlm_final_gpt']
    provider: Literal['gpt']
    model: str | None = None
    raw_output_ref: str
    displayable: bool
    point_count: int
    omitted_point_count: int = 0
    coordinate_frame: str
    units: Literal['mm','m','unknown'] = 'mm'
    validation_status: Literal['PASS','FAIL','UNVALIDATED']
    simulator_eligible: bool = False
    display_url: str
    display_sha256: str
    stages: list[str] = Field(default_factory=list)
    known_start_valid: bool = True
    coordinate_mode: Literal['absolute','relative_visualization','raw'] = 'raw'
    display_ready: bool = False
    robot_ready: bool = False
    is_robot_executable: Literal[False] = False


class RegionSelection(Schema):
    start_region: RegionId | None = None
    region_order: list[RegionId] = Field(default_factory=list)
    skip_regions: list[RegionId] = Field(default_factory=list)


class StructuredInstruction(RegionSelection):
    direction: Literal["left_to_right", "right_to_left", "top_to_bottom", "bottom_to_top"]


class Instruction(Schema):
    text: str
    structured: StructuredInstruction
    parser: str = "dummy-rule-parser"


class TrajectorySegment(Schema):
    segment_id: RegionId
    region_id: RegionId
    points: list[Point2D]
    # Travel motion is a separate future contract, not generated in this MVP.
    mode: Literal["weld"] = "weld"


class PreviewTrajectory(Schema):
    segments: list[TrajectorySegment]
    coordinate_space: Literal["image_pixel"] = "image_pixel"
    units: Literal["px"] = "px"
    is_robot_executable: Literal[False] = False
    generator: str
    artifact: ModelArtifact | None = None


class RoughTrajectory(PreviewTrajectory):
    kind: Literal["rough_preview"] = "rough_preview"


class FinalTrajectory(PreviewTrajectory):
    kind: Literal["final_preview"] = "final_preview"


class ValidationReport(Schema):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    scope: Literal["preview_geometry_only"] = "preview_geometry_only"
    robot_safety_checked: Literal[False] = False
    component_sanity_checked: bool = False
    component_tolerance_px: int = 2
    minimum_near_component_ratio: float = 0.8
    artifact: ModelArtifact | None = None


class StateEvent(Schema):
    state: WorkflowState
    reason: str
    at: datetime = Field(default_factory=utc_now)


class NativeValidationIssue(Schema):
    code: str
    classification: Literal['HARD_INVALID', 'SOFT_WARNING']
    message: str


class NativeCandidateValidation(Schema):
    status: Literal['PASS', 'WARN', 'FAIL']
    issues: list[NativeValidationIssue] = Field(default_factory=list)
    scope: Literal['native_contract_and_preview_geometry'] = 'native_contract_and_preview_geometry'
    physical_robot_executable: Literal[False] = False


class NativeCandidateSegment(Schema):
    # Native IDs/order are preserved; do not invent a confirmed region correspondence.
    segment_id: str
    source_mask_id: str
    connected_to_next: Literal[False]
    points_pixel: list[tuple[float, float]] = Field(min_length=2, max_length=4096)
    points_normalized: list[tuple[float, float]] = Field(min_length=2, max_length=4096)
    direction: Literal['forward', 'reverse'] | None = None

    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class NativeTrajectoryCandidate(Schema):
    native_artifact_id: UUID
    source_session: str  # Session basename only; private proof owns the filesystem path.
    sample_id: str
    primary_camera: str
    frame: str
    normalized_frame: str
    units: Literal['px'] = 'px'
    segments: list[NativeCandidateSegment] = Field(min_length=1)
    physical_robot_executable: Literal[False] = False


class DisplayPathSegment(Schema):
    segment_index: int
    # Invalid points break runs; independent native segments never get joined.
    runs: list[list[tuple[float, float]]]
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class ModelOutputDisplay(Schema):
    available: bool = False
    displayable: bool = False
    status: Literal['OUTPUT_MISSING', 'OUTPUT_MALFORMED', 'OUTPUT_RAW_DISPLAYABLE', 'OUTPUT_VALIDATED'] = 'OUTPUT_MISSING'
    overlay_allowed: bool = False
    sample_id: str | None = None
    primary_camera: str | None = None
    width: int | None = None
    height: int | None = None
    point_count: int = 0
    omitted_point_count: int = 0
    partial: bool = False
    segments: list[DisplayPathSegment] = Field(default_factory=list)
    mask_urls: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    # Visibility confers no approval, provenance validation or execution authority.
    guided_vla_allowed: bool = False
    simulator_allowed: Literal[False] = False


class NativeOutputReport(Schema):
    status: Literal['NATIVE_OUTPUT_MISSING', 'PARTIAL_NATIVE_OUTPUT',
                    'NATIVE_OUTPUT_READY_UNVALIDATED', 'NATIVE_OUTPUT_VALIDATED']
    native_output_generated: bool
    native_artifact_id: UUID | None = None
    source_session: str | None = None
    candidate: NativeTrajectoryCandidate | None = None
    model_output: ModelOutputDisplay | None = None
    validation: NativeCandidateValidation
    artifacts: dict[str, bool] = Field(default_factory=dict)
    preview_urls: dict[str, str] = Field(default_factory=dict)
    user_override: Literal[False] = False  # Reserved; no override action is authorized here.
    override_available: Literal[False] = False
    physical_robot_executable: Literal[False] = False


class TrajectoryClarification(Schema):
    id: UUID
    question: str = Field(min_length=1, max_length=2000)
    stage: Literal['refiner', 'planner']
    status: Literal['pending'] = 'pending'
    choices: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class WeldJob(Schema):
    schema_version: Literal[2] = 2
    id: UUID
    state: WorkflowState = WorkflowState.EMPTY
    scene: Scene | None = None
    mask: Mask | None = None
    instruction: Instruction | None = None
    rough_trajectory: RoughTrajectory | None = None
    final_trajectory: FinalTrajectory | None = None
    validation: ValidationReport | None = None
    rough_mode: Literal["baseline_2d", "native_3d"] = "baseline_2d"
    rough3d: Rough3DArtifact | None = None
    native_output: NativeOutputReport | None = None
    raw_segment_output: NativeOutputReport | None = None
    planning_status: Literal['NOT_READY', 'NEEDS_CLARIFICATION', 'READY'] = 'NOT_READY'
    trajectory_clarification: TrajectoryClarification | None = None
    clarification_history: list[UUID] = Field(default_factory=list)
    vla_prediction: VLAResultSummary | None = None
    raw_final_prediction: FinalPredictionDisplay | None = None
    previous_outputs: list[dict] = Field(default_factory=list)
    latest_final_attempt: dict | None = None
    history: list[StateEvent] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    preview_only: Literal[True] = True


class ParseInstructionRequest(Schema):
    job_id: UUID
    instruction: str = Field(min_length=1, max_length=2000)
    region_selection: RegionSelection | None = None


class PlanRequest(Schema):
    job_id: UUID


class AutomaticMaskRequest(PlanRequest):
    min_component_area: int | None = Field(default=None, ge=1)
    instruction: str = Field(default="용접할 영역을 찾아주세요.", min_length=1, max_length=2000)


class SampleSceneRequest(Schema):
    sample_id: str = Field(pattern=r"^[A-Za-z0-9_]{1,128}$")


class RoughModeRequest(PlanRequest):
    mode: Literal["baseline_2d", "native_3d"]
