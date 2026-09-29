from collections import deque
import json
from uuid import UUID, uuid4

import numpy as np
import pytest
from PIL import Image, ImageDraw

from backend.main import create_app
from backend.schemas import FinalTrajectory, Point2D, RoughTrajectory, Scene, StructuredInstruction, TrajectorySegment
from backend.services.components import detect_components
from backend.services.rough_path_client import DummyRoughPathClient
from backend.services.validation import DummyTrajectoryValidator
from backend.services.vla_client import DummyVLAClient
from conftest import png_bytes


def region_mask(count=2, *, stacked=False):
    mask = Image.new("L", (160, 90), 0)
    draw = ImageDraw.Draw(mask)
    for index in range(count):
        if stacked:
            draw.rectangle((20, 8 + 27 * index, 130, 17 + 27 * index), fill=255)
        else:
            draw.rectangle((8 + 50 * index, 20, 35 + 50 * index, 35), fill=255)
    return mask


def confirm(client, job_id, mask, **fields):
    response = client.post(
        "/api/masks/manual", data={"job_id": job_id, **fields},
        files={"file": ("regions.png", png_bytes(mask), "image/png")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def parse(client, job_id, direction="left to right", **selection):
    response = client.post("/api/instructions/parse", json={
        "job_id": job_id, "instruction": direction, "region_selection": selection,
    })
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("count,stacked", [(1, False), (2, False), (2, True), (3, True)])
def test_one_independent_segment_per_connected_component(client, scene_job, count, stacked):
    """A/B: even components with overlapping x extents must stay separate."""
    mask = region_mask(count, stacked=stacked)
    masked = confirm(client, scene_job["id"], mask)
    assert len(masked["mask"]["regions"]) == count
    parse(client, scene_job["id"])
    response = client.post("/api/weld/plan", json={"job_id": scene_job["id"]})
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["schema_version"] == 2 and job["state"] == "VALIDATED"
    labels = detect_components(mask).labels
    for name in ("rough_trajectory", "final_trajectory"):
        trajectory = job[name]
        assert trajectory["coordinate_space"] == "image_pixel"
        assert "points" not in trajectory  # No global polyline to accidentally connect regions.
        assert len(trajectory["segments"]) == count
        assert {s["region_id"] for s in trajectory["segments"]} == set(range(count))
        for segment in trajectory["segments"]:
            assert segment["mode"] == "weld"
            points = segment["points"]
            # Sample every displayed edge, not just its endpoints: no line can span the gap.
            for a, b in zip(points, points[1:]):
                for t in np.linspace(0, 1, 20):
                    x = round(a["x"] * (1 - t) + b["x"] * t)
                    y = round(a["y"] * (1 - t) + b["y"] * t)
                    assert labels[y, x] == segment["region_id"]


def test_skip_one_of_three_regions(client, scene_job):
    """C: region ID selection excludes the requested component at every model stage."""
    confirm(client, scene_job["id"], region_mask(3))
    parsed = parse(client, scene_job["id"], skip_regions=[1])
    assert parsed["instruction"]["structured"] == {
        "direction": "left_to_right", "start_region": 0, "region_order": [0, 2], "skip_regions": [1],
    }
    job = client.post("/api/weld/plan", json={"job_id": scene_job["id"]}).json()
    assert job["state"] == "VALIDATED"
    for name in ("rough_trajectory", "final_trajectory"):
        assert [s["region_id"] for s in job[name]["segments"]] == [0, 2]


def test_each_segment_direction_reverses_and_vla_keeps_correspondence():
    """D/E: per-region reversal, independent smoothing, stable segment/region mapping."""
    mask = region_mask(3)
    image = Image.new("RGB", mask.size)
    components = detect_components(mask)
    by_direction = {}
    for direction in ("left_to_right", "right_to_left"):
        instruction = StructuredInstruction(direction=direction)
        rough = DummyRoughPathClient().predict(image, mask, instruction, components)
        refined = DummyVLAClient().refine(image, mask, rough, direction, instruction)
        before = [(s.segment_id, s.region_id, s.mode) for s in rough.segments]
        after = [(s.segment_id, s.region_id, s.mode) for s in refined.segments]
        assert before == after
        for source, final in zip(rough.segments, refined.segments):
            assert source.points[0] == final.points[0] and source.points[-1] == final.points[-1]
            assert len(final.points) == 48
            xs = [p.x for p in final.points]
            assert xs == sorted(xs, reverse=direction == "right_to_left")
        by_direction[direction] = {s.region_id: s.points for s in rough.segments}
    for region_id in range(3):
        assert by_direction["left_to_right"][region_id] == list(reversed(by_direction["right_to_left"][region_id]))


def test_custom_order_and_start_region(client, scene_job):
    confirm(client, scene_job["id"], region_mask(3))
    parsed = parse(client, scene_job["id"], region_order=[2, 0], start_region=2, skip_regions=[1])
    assert parsed["instruction"]["structured"]["region_order"] == [2, 0]
    job = client.post("/api/weld/plan", json={"job_id": scene_job["id"]}).json()
    assert [s["region_id"] for s in job["final_trajectory"]["segments"]] == [2, 0]
    parsed = parse(client, scene_job["id"], start_region=1)
    assert parsed["instruction"]["structured"]["region_order"] == [1, 0, 2]


@pytest.mark.parametrize("selection", [
    {"skip_regions": [99]}, {"skip_regions": [0, 1, 2]}, {"skip_regions": [1, 1]},
    {"skip_regions": [-1]}, {"skip_regions": ["1"]}, {"skip_regions": [True]},
    {"region_order": [0, 1]}, {"region_order": [0, 1, 1]},
    {"start_region": 99}, {"start_region": 1, "skip_regions": [1]},
    {"region_order": [0, 1, 2], "start_region": 2},
])
def test_invalid_region_selection_does_not_change_state(client, scene_job, selection):
    confirm(client, scene_job["id"], region_mask(3))
    response = client.post("/api/instructions/parse", json={
        "job_id": scene_job["id"], "instruction": "left to right", "region_selection": selection,
    })
    assert response.status_code == 422
    assert client.get(f"/api/weld/{scene_job['id']}").json()["state"] == "MASK_READY"


def test_component_metadata_and_stable_ids_across_noise_filter():
    mask = Image.new("L", (15, 15), 0)
    mask.putpixel((0, 0), 255)  # Region 0, filtered by the default threshold.
    ImageDraw.Draw(mask).rectangle((5, 6, 8, 9), fill=255)  # Region 1, area 16.
    before = np.array(mask).copy()
    result = detect_components(mask)
    assert [region.region_id for region in result.regions] == [1]
    region = result.regions[0]
    assert region.pixel_area == 16
    assert region.bounding_box.model_dump() == {"x_min": 5, "y_min": 6, "x_max": 8, "y_max": 9}
    assert region.centroid == Point2D(x=6.5, y=7.5)
    assert result.discarded_component_count == 1 and result.discarded_pixels == 1
    assert result.labels[0, 0] == -1
    assert [r.region_id for r in detect_components(mask, 1).regions] == [0, 1]
    assert np.array_equal(np.asarray(mask), before)
    assert detect_components(mask).regions == result.regions


def test_eight_connected_diagonal_and_union_of_branches():
    mask = Image.fromarray(np.array([[255, 0, 255], [0, 255, 0], [0, 0, 255]], dtype=np.uint8))
    result = detect_components(mask, 1)
    assert len(result.regions) == 1 and result.regions[0].pixel_area == 4


def test_scanline_components_match_independent_flood_fill():
    random = np.random.default_rng(2026)
    for _ in range(20):
        pixels = random.random((17, 23)) > 0.78
        expected = np.full(pixels.shape, -1, dtype=np.int32)
        next_id = 0
        for y, x in np.ndindex(pixels.shape):
            if not pixels[y, x] or expected[y, x] != -1:
                continue
            queue = deque([(y, x)])
            expected[y, x] = next_id
            while queue:
                cy, cx = queue.popleft()
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < pixels.shape[0] and 0 <= nx < pixels.shape[1] and pixels[ny, nx] and expected[ny, nx] == -1:
                            expected[ny, nx] = next_id
                            queue.append((ny, nx))
            next_id += 1
        actual = detect_components(Image.fromarray(pixels.astype(np.uint8) * 255), 1)
        assert np.array_equal(actual.labels, expected)


def test_noise_filter_override_and_empty_result(client, scene_job):
    mask = Image.new("L", (160, 90), 0)
    mask.putpixel((1, 1), 255)
    response = client.post("/api/masks/manual", data={"job_id": scene_job["id"]}, files={"file": ("tiny.png", png_bytes(mask))})
    assert response.status_code == 422 and "filtering" in response.json()["detail"]
    assert client.get(f"/api/weld/{scene_job['id']}").json()["state"] == "SCENE_READY"
    masked = confirm(client, scene_job["id"], mask, min_component_area=1)
    assert masked["mask"]["regions"][0]["pixel_area"] == 1
    parse(client, scene_job["id"])
    assert client.post("/api/weld/plan", json={"job_id": scene_job["id"]}).json()["state"] == "VALIDATED"


def test_noise_threshold_environment_setting(monkeypatch, tmp_path):
    monkeypatch.setenv("WELD_MIN_COMPONENT_AREA", "25")
    app = create_app(tmp_path / "environment-storage")
    assert app.state.workflow.min_component_area == 25


def test_component_filter_does_not_renumber_or_modify_stored_mask(client, scene_job):
    mask = region_mask(1)
    mask.putpixel((1, 1), 255)
    masked = confirm(client, scene_job["id"], mask)
    assert [r["region_id"] for r in masked["mask"]["regions"]] == [1]
    assert masked["mask"]["discarded_pixels"] == 1
    from io import BytesIO
    stored = Image.open(BytesIO(client.get(masked["mask"]["image_url"]).content))
    assert np.array_equal(np.asarray(stored), np.asarray(mask))
    parse(client, scene_job["id"])
    job = client.post("/api/weld/plan", json={"job_id": scene_job["id"]}).json()
    assert job["final_trajectory"]["segments"][0]["region_id"] == 1


@pytest.mark.parametrize("corruption", ["merge", "wrong_id", "swap", "empty_segment", "no_segments", "wrong_component", "duplicate"])
def test_bad_vla_cannot_merge_reassign_or_leave_region(app, client, scene_job, corruption):
    class CorruptVLA:
        def refine(self, image, mask, rough, language, instruction):
            final = DummyVLAClient().refine(image, mask, rough, language, instruction)
            if corruption == "merge":
                final.segments[0].points += final.segments[1].points
                final.segments.pop()
            elif corruption == "wrong_id":
                final.segments[0].region_id = 99
            elif corruption == "swap":
                final.segments.reverse()
            elif corruption == "empty_segment":
                final.segments[0].points = []
            elif corruption == "no_segments":
                final.segments = []
            elif corruption == "wrong_component":
                final.segments[0].points = list(final.segments[1].points)
            else:
                final.segments[1].segment_id = final.segments[0].segment_id
            return final

    app.state.workflow.vla = CorruptVLA()
    confirm(client, scene_job["id"], region_mask(2))
    parse(client, scene_job["id"])
    response = client.post("/api/weld/plan", json={"job_id": scene_job["id"]})
    assert response.status_code == 422
    saved = client.get(f"/api/weld/{scene_job['id']}").json()
    assert saved["state"] == "VLA_REFINED" and not saved["validation"]["valid"]


def test_bad_rough_merge_is_rejected_before_vla(app, client, scene_job):
    class MergingRough:
        def predict(self, image, mask, instruction, components):
            rough = DummyRoughPathClient().predict(image, mask, instruction, components)
            rough.segments[0].points += rough.segments[1].points
            rough.segments.pop()
            return rough

    app.state.workflow.rough = MergingRough()
    confirm(client, scene_job["id"], region_mask(2))
    parse(client, scene_job["id"])
    assert client.post("/api/weld/plan", json={"job_id": scene_job["id"]}).status_code == 422
    saved = client.get(f"/api/weld/{scene_job['id']}").json()
    assert saved["state"] == "INSTRUCTION_READY" and saved["rough_trajectory"] is None


def test_component_sanity_allows_near_points_and_rejects_background():
    mask = region_mask(1)
    components = detect_components(mask)
    scene = Scene(id=uuid4(), width=160, height=90, image_url="/test")
    for y, expected_valid in [(18, True), (5, False)]:
        trajectory = RoughTrajectory(segments=[TrajectorySegment(
            segment_id=0, region_id=0, points=[Point2D(x=x, y=y) for x in range(10, 30)],
        )], generator="test")
        report = DummyTrajectoryValidator().validate(trajectory, scene, components=components, expected_segments=[(0, 0)])
        assert report.valid == expected_valid and report.component_sanity_checked
        assert report.robot_safety_checked is False


def test_v1_snapshot_is_backed_up_and_old_bridged_plan_invalidated(app, client, scene_job):
    masked = confirm(client, scene_job["id"], region_mask(2))
    legacy = dict(masked)
    legacy.pop("schema_version")
    legacy["mask"] = {key: value for key, value in legacy["mask"].items() if key not in {
        "regions", "min_component_area", "discarded_component_count", "discarded_pixels", "connectivity",
    }}
    legacy["state"] = "VALIDATED"
    legacy["rough_trajectory"] = {"points": [{"x": 10, "y": 22}, {"x": 70, "y": 22}], "coordinate_space": "image_pixels"}
    legacy["final_trajectory"] = legacy["rough_trajectory"]
    legacy["instruction"] = {"text": "left to right", "structured": {"direction": "left_to_right", "start_region": "left", "skip_regions": []}}
    job_id = UUID(scene_job["id"])
    store = app.state.workflow.storage
    raw = json.dumps(legacy)
    store.artifact_path("jobs", job_id, ".json").write_text(raw, encoding="utf-8")
    upgraded = client.get(f"/api/weld/{job_id}").json()
    assert upgraded["schema_version"] == 2 and upgraded["state"] == "MASK_READY"
    assert len(upgraded["mask"]["regions"]) == 2
    assert upgraded["instruction"] is None and upgraded["final_trajectory"] is None and upgraded["validation"] is None
    assert store.artifact_path("jobs", job_id, ".legacy-v1.json").read_text(encoding="utf-8") == raw
    assert client.post("/api/weld/plan", json={"job_id": str(job_id)}).status_code == 409
    parse(client, str(job_id))
    assert len(client.post("/api/weld/plan", json={"job_id": str(job_id)}).json()["final_trajectory"]["segments"]) == 2
