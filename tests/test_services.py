from io import BytesIO
from uuid import uuid4

import numpy as np
import pytest
from PIL import Image
from pydantic import ValidationError

from backend.orchestrator.state_machine import StateMachine, WorkflowError
from backend.schemas import Point2D, RoughTrajectory, Scene, StructuredInstruction, TrajectorySegment, WeldJob, WorkflowState
from backend.services.components import detect_components
from backend.services.mask_service import create_mask_overlay
from backend.services.rough_path_client import DummyRoughPathClient
from backend.services.validation import DummyTrajectoryValidator
from backend.services.vla_client import DummyVLAClient


def test_state_machine_cannot_skip_steps():
    job = WeldJob(id=uuid4())
    with pytest.raises(WorkflowError):
        StateMachine.advance(job, WorkflowState.MASK_READY)
    with pytest.raises(WorkflowError):
        StateMachine.replace_mask(job)
    StateMachine.advance(job, WorkflowState.SCENE_READY)
    with pytest.raises(WorkflowError):
        StateMachine.replace_instruction(job)


@pytest.mark.parametrize("coordinates", [[], [(float("nan"), 0)], [(0, float("inf"))], [(-1, 2)], [(160, 89)], [(159, 90)]])
def test_validator_rejects_empty_nonfinite_and_out_of_bounds(coordinates):
    points = [Point2D.model_construct(x=x, y=y) for x, y in coordinates]
    trajectory = RoughTrajectory.model_construct(segments=[TrajectorySegment.model_construct(segment_id=0, region_id=0, points=points)], generator="test")
    scene = Scene(id=uuid4(), width=160, height=90, image_url="/test")
    assert not DummyTrajectoryValidator().validate(trajectory, scene, components=detect_components(Image.new("L", (160, 90), 255)), expected_segments=[(0, 0)]).valid


def test_point_schema_rejects_nan():
    with pytest.raises(ValidationError):
        Point2D(x=float("nan"), y=0)


def test_smoothing_preserves_endpoints_and_order(scene_bytes, mask_bytes):
    image = Image.open(BytesIO(scene_bytes))
    mask = Image.open(BytesIO(mask_bytes))
    instruction = StructuredInstruction(direction="left_to_right")
    rough = DummyRoughPathClient().predict(image, mask, instruction, detect_components(mask, min_component_area=1))
    final = DummyVLAClient().refine(image, mask, rough, "left to right", instruction)
    assert final.segments[0].points[0] == rough.segments[0].points[0] and final.segments[0].points[-1] == rough.segments[0].points[-1]
    assert len(final.segments[0].points) == 48
    assert all(a.x <= b.x for a, b in zip(final.segments[0].points, final.segments[0].points[1:]))
    assert final.generator == "dummy-independent-segment-resample-smooth"


def test_single_pixel_mask_is_supported():
    image = Image.new("RGB", (1, 1))
    mask = Image.new("L", (1, 1), 255)
    instruction = StructuredInstruction(direction="right_to_left")
    rough = DummyRoughPathClient().predict(image, mask, instruction, detect_components(mask, min_component_area=1))
    final = DummyVLAClient().refine(image, mask, rough, "right to left", instruction)
    assert final.segments[0].points == [Point2D(x=0, y=0)]


def test_overlay_does_not_mutate_mask(scene_bytes, mask_bytes):
    image = Image.open(BytesIO(scene_bytes))
    mask = Image.open(BytesIO(mask_bytes))
    before = np.array(mask).copy()
    overlay = np.array(create_mask_overlay(image, mask))
    assert np.array_equal(np.asarray(mask), before)
    assert np.array_equal(overlay[before == 0], np.asarray(image)[before == 0])
    assert not np.array_equal(overlay[before == 255], np.asarray(image)[before == 255])
