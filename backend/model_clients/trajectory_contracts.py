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


class GPT2PredictedTrajectory(SpatialArtifact):
    """Native count is recorded, never resampled by the adapter."""
    artifact_id: UUID
    sample_id: str
    split: Literal['train','val']
    source: Literal['vlm_final_gpt2']
    provider: Literal['gpt']
    model: str = Field(pattern=r'^gpt-[a-zA-Z0-9._-]{1,120}$')
    retrieval_mode: Literal['native']
    point_count: int = Field(ge=2, le=4096)
    coordinate_frame: Literal['source_robot_frame_unaligned_with_isaac']
    units: Literal['mm']
    predicted_path_xyz_mm: list[tuple[float,float,float]]
    prediction_only: bool = False
    ground_truth_path_xyz_mm: list[tuple[float,float,float]] | None = None
    connections: list[Literal['within_segment','between_segments','unknown']]
    ade_mm: float | None = Field(default=None,ge=0)
    fde_mm: float | None = Field(default=None,ge=0)
    simulation_only: Literal[True] = True
    physical_robot_executable: Literal[False] = False

    @model_validator(mode='after')
    def native_count(self):
        if (len(self.predicted_path_xyz_mm) != self.point_count or

                len(self.connections) != self.point_count-1):
            raise ValueError('Native GPT2 point/connection count differs')
        if self.prediction_only:
            if any(v is not None for v in (self.ground_truth_path_xyz_mm,self.ade_mm,self.fde_mm)):
                raise ValueError('Prediction-only must not fabricate evaluation')
        elif self.ground_truth_path_xyz_mm is None or len(self.ground_truth_path_xyz_mm)!=self.point_count or self.ade_mm is None or self.fde_mm is None:
            raise ValueError('Evaluation export requires real GT/metrics')
        return self
