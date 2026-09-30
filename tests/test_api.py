from io import BytesIO
from uuid import UUID, uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.main import create_app
from backend.schemas import FinalTrajectory, Point2D, TrajectorySegment
from tests.conftest import png_bytes


def test_health_and_cors(client):
    response = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 200
    assert response.json()["mode"] == "dummy_preview"
    assert response.json()["robot_execution_enabled"] is False
    assert response.json()["isaac"]["enabled"] is False
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_scene_upload(client, scene_job):
    assert scene_job["state"] == "SCENE_READY"
    assert scene_job["preview_only"] is True
    scene = scene_job["scene"]
    assert (scene["width"], scene["height"]) == (160, 90)
    with Image.open(BytesIO(client.get(scene["image_url"]).content)) as image:
        assert image.mode == "RGB"
        assert image.size == (160, 90)
    assert [event["state"] for event in scene_job["history"]] == ["EMPTY", "SCENE_READY"]


def test_scene_exif_orientation_normalized(client):
    image = Image.new("RGB", (160, 90))
    exif = image.getexif()
    exif[274] = 6
    buffer = BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    response = client.post("/api/scenes/upload", files={"file": ("rotated.jpg", buffer.getvalue(), "image/jpeg")})
    assert response.status_code == 201
    assert response.json()["scene"]["width"] == 90
    assert response.json()["scene"]["height"] == 160


@pytest.mark.parametrize("content", [b"", b"not an image", b"<svg></svg>"])
def test_bad_scene(client, content):
    assert client.post("/api/scenes/upload", files={"file": ("bad.png", content)}).status_code == 422


def test_manual_mask_and_separate_overlay(client, mask_job):
    assert mask_job["state"] == "MASK_READY"
    mask = mask_job["mask"]
    assert mask["mask_source"] == "manual"
    assert mask["role"] == "2d_visual_conditioning"
    content = client.get(mask["image_url"]).content
    with Image.open(BytesIO(content)) as image:
        assert image.mode == "L"
        assert image.size == (160, 90)
        assert set(np.unique(image)) == {0, 255}
        assert mask["selected_pixels"] == np.count_nonzero(image)
    with Image.open(BytesIO(client.get(mask["overlay_url"]).content)) as overlay:
        assert overlay.mode == "RGB"
        assert overlay.size == (160, 90)
    assert client.get(mask["image_url"]).content == content


@pytest.mark.parametrize("image, message", [
    (Image.new("L", (159, 90), 255), "dimensions"),
    (Image.new("L", (160, 90), 0), "empty"),
    (Image.new("L", (160, 90), 128), "0 and 255"),
    (Image.new("RGB", (160, 90), (255, 0, 0)), "grayscale"),
    (Image.new("RGBA", (160, 90), (255, 255, 255, 0)), "opaque"),
])
def test_bad_mask_rejected_without_state_change(client, scene_job, image, message):
    response = client.post("/api/masks/manual", data={"job_id": scene_job["id"]}, files={"file": ("mask.png", png_bytes(image))})
    assert response.status_code == 422
    assert message in response.json()["detail"]
    assert client.get(f"/api/weld/{scene_job['id']}").json()["state"] == "SCENE_READY"


def test_opaque_browser_rgba_mask_is_saved_as_grayscale(client, scene_job):
    response = client.post("/api/masks/manual", data={"job_id": scene_job["id"]}, files={"file": ("mask.png", png_bytes(Image.new("RGBA", (160, 90), (255, 255, 255, 255))))})
    assert response.status_code == 200
    with Image.open(BytesIO(client.get(response.json()["mask"]["image_url"]).content)) as image:
        assert image.mode == "L"
        assert set(np.unique(image)) == {255}


def test_mask_requires_png(client, scene_job):
    buffer = BytesIO()
    Image.new("L", (160, 90), 255).save(buffer, format="JPEG")
    assert client.post("/api/masks/manual", data={"job_id": scene_job["id"]}, files={"file": ("mask.jpg", buffer.getvalue())}).status_code == 422


@pytest.mark.parametrize("text,direction", [
    ("왼쪽에서 오른쪽으로 용접해", "left_to_right"),
    ("오른쪽에서 왼쪽으로 용접해", "right_to_left"),
    ("Weld left to right", "left_to_right"),
])
def test_instruction_parsing(client, mask_job, text, direction):
    response = client.post("/api/instructions/parse", json={"job_id": mask_job["id"], "instruction": text})
    assert response.status_code == 200
    assert response.json()["state"] == "INSTRUCTION_READY"
    assert response.json()["instruction"]["structured"] == {"direction": direction, "start_region": 0, "region_order": [0], "skip_regions": []}


@pytest.mark.parametrize("text", ["   ", "용접해", "왼쪽에서 오른쪽으로 갔다가 오른쪽에서 왼쪽으로", "왼쪽에서 오른쪽으로 가운데 빼고 용접해"])
def test_unsupported_instructions_are_not_guessed(client, mask_job, text):
    assert client.post("/api/instructions/parse", json={"job_id": mask_job["id"], "instruction": text}).status_code == 422


@pytest.mark.parametrize("endpoint", ["rough", "refine", "validate"])
def test_invalid_model_step_order(client, scene_job, endpoint):
    response = client.post(f"/api/weld/{scene_job['id']}/{endpoint}")
    assert response.status_code == 409


def test_plan_and_instruction_require_mask(client, scene_job):
    assert client.post("/api/weld/plan", json={"job_id": scene_job["id"]}).status_code == 409
    assert client.post("/api/instructions/parse", json={"job_id": scene_job["id"], "instruction": "left to right"}).status_code == 409


def test_plan_requires_instruction_and_vla_requires_rough(client, mask_job, instructed_job):
    assert client.post(f"/api/weld/{instructed_job['id']}/refine").status_code == 409
    # Start a fresh automatic mask to explicitly invalidate the parsed instruction.
    assert client.post("/api/masks/automatic", json={"job_id": mask_job["id"]}).status_code == 200
    assert client.post("/api/weld/plan", json={"job_id": mask_job["id"]}).status_code == 409


def test_full_plan_and_idempotent_fetch(client, instructed_job):
    response = client.post("/api/weld/plan", json={"job_id": instructed_job["id"]})
    assert response.status_code == 200
    result = response.json()
    assert result["state"] == "VALIDATED"
    assert result["validation"] == {"valid": True, "errors": [], "scope": "preview_geometry_only", "robot_safety_checked": False, "component_sanity_checked": True, "component_tolerance_px": 2, "minimum_near_component_ratio": 0.8}
    for field in ("rough_trajectory", "final_trajectory"):
        trajectory = result[field]
        assert trajectory["coordinate_space"] == "image_pixel"
        assert trajectory["is_robot_executable"] is False
        assert trajectory["units"] == "px"
        assert len(trajectory["segments"][0]["points"]) > 1
        assert all(0 <= p["x"] <= 159 and 0 <= p["y"] <= 89 for p in trajectory["segments"][0]["points"])
    assert len(result["final_trajectory"]["segments"][0]["points"]) > len(result["rough_trajectory"]["segments"][0]["points"])
    assert [event["state"] for event in result["history"]] == ["EMPTY", "SCENE_READY", "MASK_READY", "INSTRUCTION_READY", "ROUGH_PATH_READY", "VLA_REFINED", "VALIDATED"]
    assert client.get(f"/api/weld/{result['id']}").json() == result
    assert client.post("/api/weld/plan", json={"job_id": result["id"]}).json() == result


def test_separate_steps_and_right_to_left(client, mask_job):
    job_id = mask_job["id"]
    client.post("/api/instructions/parse", json={"job_id": job_id, "instruction": "오른쪽에서 왼쪽으로 용접해"})
    rough = client.post(f"/api/weld/{job_id}/rough").json()
    assert rough["state"] == "ROUGH_PATH_READY"
    points = rough["rough_trajectory"]["segments"][0]["points"]
    assert points[0]["x"] > points[-1]["x"]
    assert client.post(f"/api/weld/{job_id}/rough").status_code == 409
    refined = client.post(f"/api/weld/{job_id}/refine").json()
    assert refined["state"] == "VLA_REFINED"
    assert refined["final_trajectory"]["segments"][0]["points"][0] == points[0]
    assert refined["final_trajectory"]["segments"][0]["points"][-1] == points[-1]
    assert client.post(f"/api/weld/{job_id}/validate").json()["state"] == "VALIDATED"


def test_upstream_edits_clear_downstream(client, instructed_job, mask_bytes):
    job_id = instructed_job["id"]
    client.post("/api/weld/plan", json={"job_id": job_id})
    parsed = client.post("/api/instructions/parse", json={"job_id": job_id, "instruction": "right to left"}).json()
    assert parsed["state"] == "INSTRUCTION_READY"
    assert parsed["rough_trajectory"] is None and parsed["final_trajectory"] is None and parsed["validation"] is None
    client.post("/api/weld/plan", json={"job_id": job_id})
    remasked = client.post("/api/masks/manual", data={"job_id": job_id}, files={"file": ("mask.png", mask_bytes)}).json()
    assert remasked["state"] == "MASK_READY"
    assert remasked["instruction"] is None and remasked["final_trajectory"] is None
    assert client.post("/api/weld/plan", json={"job_id": job_id}).status_code == 409


def test_automatic_mask_uses_same_downstream_contract(client, scene_job):
    masked = client.post("/api/masks/automatic", json={"job_id": scene_job["id"]}).json()
    assert masked["mask"]["mask_source"] == "automatic"
    assert masked["mask"]["encoding"] == "grayscale_png_0_255"
    client.post("/api/instructions/parse", json={"job_id": scene_job["id"], "instruction": "left to right"})
    assert client.post("/api/weld/plan", json={"job_id": scene_job["id"]}).json()["state"] == "VALIDATED"


def test_persistence_across_app_restart(app, client, instructed_job):
    job_id = instructed_job["id"]
    original = client.post("/api/weld/plan", json={"job_id": job_id}).json()
    with TestClient(create_app(app.state.workflow.storage.root)) as restarted:
        assert restarted.get(f"/api/weld/{job_id}").json() == original
    export = app.state.workflow.storage.artifact_path("trajectories", UUID(job_id), ".json")
    assert '"coordinate_space": "image_pixel"' in export.read_text()


def test_adapter_validation_failure_cannot_reach_validated(app, client, instructed_job):
    class BadVLA:
        def refine(self, *args):
            return FinalTrajectory(segments=[TrajectorySegment(segment_id=0, region_id=0, points=[Point2D(x=9999, y=0)])], generator="test-invalid-adapter")

    app.state.workflow.vla = BadVLA()
    response = client.post("/api/weld/plan", json={"job_id": instructed_job["id"]})
    assert response.status_code == 422
    saved = client.get(f"/api/weld/{instructed_job['id']}").json()
    assert saved["state"] == "VLA_REFINED"
    assert saved["validation"]["valid"] is False


def test_unknown_ids_and_path_traversal(client):
    assert client.get(f"/api/weld/{uuid4()}").status_code == 404
    assert client.get(f"/api/scenes/{uuid4()}/image").status_code == 404
    assert client.get("/api/scenes/not-a-uuid/image").status_code == 422
    assert client.post("/api/weld/plan", json={"job_id": str(uuid4()), "state": "VALIDATED"}).status_code == 422
