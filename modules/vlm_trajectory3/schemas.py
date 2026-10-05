from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RefinedTask(BaseModel):
    status: Literal["ready", "needs_clarification"]
    refined_instruction_ko: str
    refined_instruction_en: str
    operation: str = "weld"
    target_description_ko: str
    target_description_en: str
    workpieces: list[str] = Field(default_factory=list)
    joint_type: str = "unknown"
    thickness: str = "unknown"
    object_size: str = "unknown"
    target_mask_ids: list[str] = Field(default_factory=list)
    path_shape: str = "unspecified"
    continuity: str = "unspecified"
    direction_preference: str = "unspecified"
    assumptions_ko: list[str] = Field(default_factory=list)
    assumptions_en: list[str] = Field(default_factory=list)
    clarification_question_ko: str | None = None
    search_text_ko: str


class SegmentDecision(BaseModel):
    segment_id: str
    direction: Literal["forward", "reverse"]
    weld_enabled: bool
    purpose_ko: str
    purpose_en: str


class OperationStep(BaseModel):
    order: int
    action: Literal["approach", "follow_segment", "reposition", "retract", "finish"]
    segment_id: str | None = None
    weld_enabled: bool
    instruction_ko: str
    instruction_en: str


class DetailedPlan(BaseModel):
    status: Literal["ready", "needs_clarification"]
    task_summary_ko: str
    task_summary_en: str
    target_joint_id: str
    grounded_mask_ids: list[str] = Field(default_factory=list)
    view_relationship_ko: str
    view_relationship_en: str
    reference_motion_pattern_ko: list[str] = Field(default_factory=list)
    reference_motion_pattern_en: list[str] = Field(default_factory=list)
    segment_decisions: list[SegmentDecision] = Field(default_factory=list)
    operations: list[OperationStep] = Field(default_factory=list)
    motion_constraints_ko: list[str] = Field(default_factory=list)
    motion_constraints_en: list[str] = Field(default_factory=list)
    completion_condition_ko: str
    completion_condition_en: str
    uncertainties_ko: list[str] = Field(default_factory=list)
    uncertainties_en: list[str] = Field(default_factory=list)
    clarification_question_ko: str | None = None
