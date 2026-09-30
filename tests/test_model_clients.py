import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image, ImageDraw

from backend.model_clients.config import ModelSettings
from backend.model_clients.contracts import ModelFault
from backend.model_clients.runtime import ModelRuntime
from backend.model_clients.segmentation import RealVlmSegmentationClient
from backend.model_clients.centerline import component_paths
from backend.model_clients.rough import VlmTrajectoryClient
from backend.schemas import StructuredInstruction
from backend.services.components import detect_components


@pytest.fixture
def configured(tmp_path):
    repo = tmp_path / "external"
    (repo / "config").mkdir(parents=True)
    (repo / "mask.py").write_text("# stub", encoding="utf-8")
    (repo / "cot.py").write_text("# stub", encoding="utf-8")
    (repo / "config/config.yaml").write_text("{}", encoding="utf-8")
    return ModelSettings(stage="segment", backend="real", repository=repo, python=Path(sys.executable),
                         api_key="private-test-key", reference_mode="none")


def test_segment_worker_contract_and_no_secret_in_manifest(configured, tmp_path):
    def run(args, **kwargs):
        assert args[0] == sys.executable and args[1] == "-B" and kwargs["shell"] is False
        assert kwargs["timeout"] == 120 and kwargs["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
        path = Path(args[-1]); request = json.loads(path.read_text(encoding="utf-8"))
        assert "private-test-key" not in path.read_text(encoding="utf-8")
        assert request["instruction"] == "find weld"
        mask = Image.new("L", (80, 40), 0)
        draw = ImageDraw.Draw(mask); draw.rectangle((3, 3, 20, 6), fill=255); draw.rectangle((55, 30, 74, 34), fill=255)
        mask.save(path.parent / "mask.png")
        (path.parent / "output.json").write_text(json.dumps({"model_name": "test-model", "model_version": "test-v1", "source_sha256": "f" * 64}))
        return SimpleNamespace(returncode=0)
    runtime = ModelRuntime(configured, cache=tmp_path / "cache", run=run)
    assert runtime.status()["state"] == "UNVERIFIED"
    mask = RealVlmSegmentationClient(runtime).segment(Image.new("RGB", (80, 40)), instruction="find weld")
    assert mask.size == (80, 40) and set(np.unique(mask)) == {0, 255}
    assert mask.info["model_provenance"].reference_mode == "none"
    assert runtime.status()["ready"] is True
    assert "private-test-key" not in str(runtime.status())


@pytest.mark.parametrize("size,mode,value", [((40, 20), "L", 255), ((80, 40), "L", 0), ((80, 40), "L", 127), ((80, 40), "RGB", "white")])
def test_segment_rejects_bad_outputs(configured, tmp_path, size, mode, value):
    def run(args, **_):
        directory = Path(args[-1]).parent
        Image.new(mode, size, value).save(directory / "mask.png")
        (directory / "output.json").write_text('{}')
        return SimpleNamespace(returncode=0)
    runtime = ModelRuntime(configured, cache=tmp_path / "cache", run=run)
    with pytest.raises(ModelFault, match="모델 출력"):
        RealVlmSegmentationClient(runtime).segment(Image.new("RGB", (80, 40)))
    assert runtime.status()["code"] == "MODEL_OUTPUT_INVALID"


def test_status_does_not_start_worker_and_timeout_does_not_retry(configured, tmp_path):
    calls = []
    def timeout(*args, **kwargs):
        calls.append(1)
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])
    runtime = ModelRuntime(configured, cache=tmp_path, run=timeout)
    for _ in range(3):
        assert runtime.status()["configured"]
    assert calls == []
    with pytest.raises(ModelFault) as error:
        runtime.infer(Image.new("RGB", (20, 20)), {})
    assert error.value.code == "MODEL_TIMEOUT" and calls == [1]
    assert runtime.status()["ready"] is False
    assert not replace(configured, python=None).configured()
    assert not replace(configured, reference_mode="").configured()


def test_centerlines_keep_components_skip_and_original_pixels():
    mask = Image.new("L", (100, 60)); draw = ImageDraw.Draw(mask)
    draw.line([(5, 15), (35, 15)], fill=255, width=7)
    draw.line([(60, 40), (90, 40)], fill=255, width=7)
    components = detect_components(mask)
    paths = component_paths(components, [1, 0])
    assert len(paths) == 2
    for path, region in zip(paths, [1, 0]):
        assert len(path) >= 2
        assert all(components.labels[round(y), round(x)] == region for x, y in path)
        assert path[0][0] < path[-1][0]
    assert len(component_paths(components, [1])) == 1


@pytest.mark.parametrize("shape", ["branch", "ring", "dot"])
def test_centerlines_reject_ambiguous_shapes(shape):
    mask = Image.new("L", (80, 80)); draw = ImageDraw.Draw(mask)
    if shape == "branch":
        draw.line([(10, 40), (70, 40)], fill=255, width=7)
        draw.line([(40, 10), (40, 70)], fill=255, width=7)
    elif shape == "ring":
        draw.rectangle((10, 10, 70, 70), outline=255, width=7)
    else:
        draw.rectangle((30, 30, 38, 38), fill=255)
    components = detect_components(mask)
    with pytest.raises(ModelFault) as error:
        component_paths(components, [0])
    assert error.value.code == "MODEL_INPUT_INVALID"


def rough_output():
    return {"rough_action": {"coordinate_frame": "mask_normalized:web", "primary_camera": "web", "segments": [
        {"segment_id": "segment_0", "source_mask_id": "web:polyline_0", "connected_to_next": False,
         "points_pixel": [[10, 20], [40, 20]], "points_normalized": [[.1, .2], [.4, .2]]},
        {"segment_id": "segment_1", "source_mask_id": "web:polyline_1", "connected_to_next": False,
         "points_pixel": [[60, 70], [90, 70]], "points_normalized": [[.6, .7], [.9, .7]]}]},
        "refined_task": {"status": "ready", "target_mask_ids": ["web:polyline_0", "web:polyline_1"]},
        "plan": {"status": "ready", "grounded_mask_ids": ["web:polyline_0", "web:polyline_1"],
                 "segment_decisions": [{"segment_id": f"segment_{i}", "direction": "forward", "weld_enabled": True} for i in range(2)],
                 "operations": [{"order": i + 1, "action": "follow_segment", "segment_id": f"segment_{i}", "weld_enabled": True} for i in range(2)]}}


def test_rough_preserves_pixels_and_selected_region_correspondence(configured):
    client = VlmTrajectoryClient(ModelRuntime(replace(configured, stage="rough")))
    result = client.convert(rough_output(), (100, 100), StructuredInstruction(direction="left_to_right", region_order=[3, 0]))
    assert [s.region_id for s in result.segments] == [3, 0]
    assert result.segments[0].points[0].x == 10
    assert result.coordinate_space == "image_pixel" and result.is_robot_executable is False


@pytest.mark.parametrize("mutation", ["bridge", "normalization", "duplicate", "skip", "order", "direction", "nan", "frame"])
def test_rough_rejects_bad_model_correspondence(configured, mutation):
    output = rough_output()
    if mutation == "bridge": output["rough_action"]["segments"][0]["connected_to_next"] = True
    if mutation == "normalization": output["rough_action"]["segments"][0]["points_normalized"][0] = [10, 20]
    if mutation == "duplicate": output["plan"]["segment_decisions"][1]["segment_id"] = "segment_0"
    if mutation == "skip": output["plan"]["segment_decisions"][0]["weld_enabled"] = False
    if mutation == "order": output["plan"]["operations"][0]["segment_id"] = "segment_1"
    if mutation == "direction": output["plan"]["segment_decisions"][0]["direction"] = "reverse"
    if mutation == "nan": output["rough_action"]["segments"][0]["points_pixel"][0][0] = float("nan")
    if mutation == "frame": output["rough_action"]["coordinate_frame"] = "robot"
    with pytest.raises(ValueError):
        VlmTrajectoryClient(ModelRuntime(configured)).convert(output, (100, 100), StructuredInstruction(direction="left_to_right", region_order=[0, 1]))


def test_real_adapters_with_fake_workers_round_trip_edit_and_skip(configured, tmp_path):
    from backend.orchestrator.workflow import Workflow
    from backend.services.storage import LocalStorage
    from tests.conftest import png_bytes
    seen = []
    def run(args, **kwargs):
        directory = Path(args[-1]).parent
        request = json.loads((directory / "input.json").read_text(encoding="utf-8"))
        seen.append(request)
        if request["stage"] == "segment":
            mask = Image.new("L", (100, 100)); draw = ImageDraw.Draw(mask)
            draw.rectangle((10, 17, 40, 23), fill=255); draw.rectangle((60, 67, 90, 73), fill=255)
            mask.save(directory / "mask.png")
            output = {}
        else:
            count = len(request["polylines"])
            output = rough_output()
            output["rough_action"]["segments"] = []
            for i, path in enumerate(request["polylines"]):
                points = [path[0], path[-1]]
                output["rough_action"]["segments"].append({"segment_id": f"segment_{i}", "source_mask_id": f"web:polyline_{i}",
                    "connected_to_next": False, "points_pixel": points, "points_normalized": (np.asarray(points) / 100).tolist()})
            output["plan"]["segment_decisions"] = output["plan"]["segment_decisions"][:count]
            output["plan"]["operations"] = output["plan"]["operations"][:count]
            output["plan"]["grounded_mask_ids"] = output["plan"]["grounded_mask_ids"][:count]
            output["refined_task"]["target_mask_ids"] = output["refined_task"]["target_mask_ids"][:count]
        output.update(model_name="offline-model", model_version="offline-v1", source_sha256="a" * 64)
        (directory / "output.json").write_text(json.dumps(output))
        return SimpleNamespace(returncode=0)
    workflow = Workflow(LocalStorage(tmp_path / "storage"),
        segmentation=RealVlmSegmentationClient(ModelRuntime(configured, cache=tmp_path / "segment", run=run)),
        rough=VlmTrajectoryClient(ModelRuntime(replace(configured, stage="rough"), cache=tmp_path / "rough", run=run)))
    job = workflow.upload_scene(png_bytes(Image.new("RGB", (100, 100))))
    job = workflow.set_mask(job.id, instruction="자동으로 찾아줘")
    assert job.mask.mask_source == "vlm_segment" and len(job.mask.regions) == 2
    original_id = job.mask.id
    workflow.parse_instruction(job.id, "왼쪽에서 오른쪽으로 용접해")
    progress = []
    job = workflow.plan(job.id, progress=lambda name, done, _: progress.append((name, done)))
    assert job.validation.valid and job.final_trajectory.generator.startswith("dummy")
    assert progress == [(name, done) for name in ("rough", "refine", "validate") for done in (False, True)]
    assert job.rough_trajectory.artifact.provenance.source_mask_id == original_id
    assert workflow.get_job(job.id).rough_trajectory.artifact == job.rough_trajectory.artifact
    edited = Image.new("L", (100, 100)); draw = ImageDraw.Draw(edited)
    draw.rectangle((10, 17, 28, 23), fill=255); draw.rectangle((60, 67, 90, 73), fill=255)
    job = workflow.set_mask(job.id, png_bytes(edited), edited_from_mask_id=original_id)
    assert job.mask.mask_source == "manual_edited" and job.mask.edited_from_mask_id == original_id
    previous = json.loads(workflow.storage.artifact_path("masks", original_id, ".json").read_text(encoding="utf-8"))
    assert previous["mask_source"] == "vlm_segment" and previous["artifact"]["provenance"]["model_name"] == "offline-model"
    assert job.rough_trajectory is job.final_trajectory is job.validation is None
    workflow.apply_instruction(job.id, "두 번째 영역 제외", StructuredInstruction(direction="left_to_right", skip_regions=[1]))
    job = workflow.plan(job.id)
    assert [s.region_id for s in job.rough_trajectory.segments] == [0]
    assert max(p.x for p in job.rough_trajectory.segments[0].points) <= 28
    assert len([r for r in seen if r["stage"] == "segment"]) == 1
    assert job.final_trajectory.artifact.provenance.source_mask_id == job.mask.id
    assert job.final_trajectory.is_robot_executable is False


def test_model_errors_are_sanitized_in_http_and_agent(configured, tmp_path):
    from backend.agent.config import public_error
    from backend.main import create_app
    from backend.orchestrator.workflow import Workflow
    from backend.services.storage import LocalStorage
    from fastapi.testclient import TestClient
    from tests.agent_fakes import FakeSimulator
    from tests.conftest import png_bytes
    runtime = ModelRuntime(replace(configured, python=None))
    workflow = Workflow(LocalStorage(tmp_path / "storage"), segmentation=RealVlmSegmentationClient(runtime))
    job = workflow.upload_scene(png_bytes(Image.new("RGB", (100, 100))))
    with TestClient(create_app(workflow=workflow, simulator=FakeSimulator())) as client:
        status = client.get("/api/models/status").json()
        assert status["segment"]["state"] == "NOT_CONFIGURED" and status["vla"]["backend"] == "dummy"
        result = client.post("/api/masks/automatic", json={"job_id": str(job.id)})
        assert result.status_code == 503 and result.json()["code"] == "MODEL_NOT_CONFIGURED"
        assert workflow.get_job(job.id).state == "SCENE_READY"
        assert str(configured.repository) not in result.text + json.dumps(status)
    for code in ModelFault.MESSAGES:
        assert public_error(ModelFault(code)).code == code
