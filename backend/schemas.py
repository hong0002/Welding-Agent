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


class Scene(Schema):
    id: UUID
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    image_url: str
    color_mode: Literal["RGB"] = "RGB"
    artifact: ModelArtifact | None = None


class Mask(Schema):
    id: UUID
    scene_id: UUID
    width: int
    height: int
    mask_source: Literal["manual", "automatic", "vlm_segment", "manual_edited"]
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


class RegionSelection(Schema):
    start_region: RegionId | None = None
    region_order: list[RegionId] = Field(default_factory=list)
    skip_regions: list[RegionId] = Field(default_factory=list)


class StructuredInstruction(RegionSelection):
    direction: Literal["left_to_right", "right_to_left"]


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
