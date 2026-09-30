"""Private spatial artifacts. These are never image-pixel FinalTrajectory or robot commands."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SpatialArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)
    is_robot_executable: Literal[False] = False


class ReferenceSegment3D(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    segment_id: str
    source_segment_id: str
    connected_to_next: Literal[False]
    source_point_count: int = Field(ge=2)
    source_length_mm: float = Field(ge=0)
    teaching_direction: str
    teaching_direction_ko: str = ""
    teaching_direction_en: str = ""
    points_xyz_mm: list[tuple[float, float, float]] = Field(min_length=2)


class ReferenceTrajectory3D(SpatialArtifact):
    schema_version: Literal["welding-reference-trajectory-3d-v1"]
    source_sample_id: str
    selection_method: str
    coordinate_frame: Literal["retrieved_teaching_start_relative"]
    source_coordinate_frame: str
    unit: Literal["mm"]
    registered_to_query: Literal[False]
    target_point_count: int = Field(ge=2)
    actual_point_count: int = Field(ge=2)
    source_trajectory: dict
    segments: list[ReferenceSegment3D] = Field(min_length=1)

    @model_validator(mode="after")
    def correspondence(self):
        if (sum(len(s.points_xyz_mm) for s in self.segments) != self.actual_point_count or
                len({s.segment_id for s in self.segments}) != len(self.segments)):
            raise ValueError("Invalid reference segment/count contract")
        return self


class VLAPredictedTrajectory(SpatialArtifact):
    sample_id: str
    split: Literal["train", "val"]
    predicted_path_xyz_mm: list[tuple[float, float, float]] = Field(min_length=9, max_length=9)
    ground_truth_path_xyz_mm: list[tuple[float, float, float]] = Field(min_length=9, max_length=9)
    coordinate_frame: str = Field(min_length=1)
    units: Literal["mm"] = "mm"
    ade_mm: float = Field(ge=0)
    fde_mm: float = Field(ge=0)
    task_metadata: dict
    input_sources: dict | list | str | None = None
    guidance: dict | list | str | None = None
    guidance_mode: str | None = None
    cot_delivery: dict | None = None
