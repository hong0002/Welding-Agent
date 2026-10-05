"""Private spatial artifacts. These are never image-pixel FinalTrajectory or robot commands."""
from typing import Literal
from uuid import UUID, uuid4

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
    artifact_id: UUID = Field(default_factory=uuid4)
    sample_id: str
    split: Literal["train", "val"]
    model: str | None = None
    point_count: Literal[9] = 9
    simulation_only: Literal[True] = True
    physical_robot_executable: Literal[False] = False
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


class GPTPredictedTrajectory(SpatialArtifact):
    retrieval_mode: Literal['segment2_adapter','local','none'] | None = None
    artifact_id: UUID
    sample_id: str
    split: Literal['train','val']
    source: Literal['vlm_final_gpt']
    provider: Literal['gpt']
    model: str = Field(pattern=r'^gpt-[a-zA-Z0-9._-]{1,120}$')
    point_count: Literal[33]
    coordinate_frame: Literal['source_robot_frame_unaligned_with_isaac']
    units: Literal['mm']
    predicted_path_xyz_mm: list[tuple[float,float,float]] = Field(min_length=33,max_length=33)
    ground_truth_path_xyz_mm: list[tuple[float,float,float]] = Field(min_length=33,max_length=33)
    connections: list[Literal['within_segment','between_segments','unknown']] = Field(min_length=32,max_length=32)
    ade_mm: float = Field(ge=0)
    fde_mm: float = Field(ge=0)
    simulation_only: Literal[True] = True
    physical_robot_executable: Literal[False] = False
