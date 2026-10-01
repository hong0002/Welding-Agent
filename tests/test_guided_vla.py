"""Owned tiny fixtures and injected HTTP/native processes. Never contact any model server."""
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from uuid import uuid4

import numpy as np
import httpx
from PIL import Image, ImageDraw
import pytest
import yaml

from backend.model_clients.config import ModelSettings
from backend.model_clients.guided_vla import (
    GuidedVLAClient, GuidedVLAError, GuidedVLASettings, HTTPGuidedTransport, serialize_guidance, validate_response, validate_cot_delivery,
)
from backend.model_clients.native import NativeBinding, NativeRuntime, read_native_result
from backend.model_clients.native_rough3d import NativeRough3DClient, NativeRough2DClient
from backend.model_clients.trajectory_contracts import ReferenceTrajectory3D, VLAPredictedTrajectory
from backend.schemas import Mask, Scene, WeldJob
from backend.services.components import detect_components


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def response():
    return {"sample_id": "SAMPLE_1", "split": "train", "coordinate_frame": "source_robot_frame_unaligned_with_isaac",
            "predicted_path_xyz_mm": [[i, 2*i, 3*i] for i in range(9)],
            "ground_truth_path_xyz_mm": [[i+1, 2*i+1, 3*i+1] for i in range(9)],
            "ade_mm": 1, "fde_mm": 2, "task_metadata": {}, "guidance_mode": "fixture_guided"}


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    for module in ("guided_vla", "native_rough3d", "native"):
        monkeypatch.setattr(f"backend.model_clients.{module}.ROOT", tmp_path)
    return create_inputs(tmp_path)


def create_inputs(tmp_path):
    """Tiny offline native artifacts, also used by the browser test factory."""
    source = tmp_path / "dataset/2.데이터(NIA)/Training/01.원천데이터/TS_Butt/03/SAMPLE_1/SAMPLE_1_F_Color.png"
    source.parent.mkdir(parents=True)
    scene = Image.new("RGB", (100, 100), "gray")
    scene.save(source)
    label = tmp_path / "dataset/2.데이터(NIA)/Training/02.라벨링데이터/TL_Butt/03/SAMPLE_1/SAMPLE_1.json"
    save(label, {"info": {"gid": "SAMPLE_1"}, "rgb_images": [{"filename": source.name, "rgb_width": 100, "rgb_height": 100}]})
    binding = NativeBinding(sample_id="SAMPLE_1", camera="F", image=source)
    binding_path = tmp_path / "binding.json"
    save(binding_path, binding.model_dump(mode="json"))
    storage = tmp_path / "storage"
    scene_id, mask_id, job_id = uuid4(), uuid4(), uuid4()
    for folder in ("scenes", "masks", "jobs"):
        (storage / folder).mkdir(parents=True)
    scene.save(storage / "scenes" / f"{scene_id}.png")
    mask = Image.new("L", (100, 100))
    ImageDraw.Draw(mask).line([(10, 20), (90, 20)], fill=255, width=5)
    mask_path = storage / "masks" / f"{mask_id}.png"
    mask.save(mask_path)
    components = detect_components(mask)
    metadata = Mask(id=mask_id, scene_id=scene_id, width=100, height=100, mask_source="manual_edited",
                    approved=True, approved_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
                    image_url="/mask", overlay_url="/overlay", selected_pixels=int(np.count_nonzero(mask)),
                    regions=components.regions, min_component_area=16)
    job = WeldJob(id=job_id, scene=Scene(id=scene_id, width=100, height=100, image_url="/image"), mask=metadata)
    job_path = storage / "jobs" / f"{job.id}.json"
    save(job_path, job.model_dump(mode="json"))
    points = [[10+i*10, 20] for i in range(9)]
    guidance = {"schema_version": "welding-image-guidance-v1", "coordinate_frame_pixel": "image_pixel:F",
                "coordinate_frame_normalized": "image_normalized:F", "primary_camera": "F",
                "image_size": {"width": 100, "height": 100}, "target_point_count": 9, "actual_point_count": 9,
                "point_budget_overflow": False, "segment_point_counts": [9],
                "segments": [{"segment_id": "segment_0", "source_mask_id": "F:polyline_0", "connected_to_next": False,
                              "points_pixel": points, "points_normalized": [[x/100, y/100] for x, y in points]}]}
    reference = {"schema_version": "welding-reference-trajectory-3d-v1", "source_sample_id": "REF_1",
                 "selection_method": "highest_ranked_matching_segment_count", "coordinate_frame": "retrieved_teaching_start_relative",
                 "source_coordinate_frame": "source_start_relative_mm", "unit": "mm", "registered_to_query": False,
                 "target_point_count": 9, "actual_point_count": 9, "source_trajectory": {"dimension": 6},
                 "segments": [{"segment_id": "reference_segment_0", "source_segment_id": "segment_0", "connected_to_next": False,
                               "source_point_count": 20, "source_length_mm": 20, "teaching_direction": "positive_x",
                               "points_xyz_mm": [[i, i, i] for i in range(9)]}]}
    plan = {"status": "ready", "grounded_mask_ids": ["F:polyline_0"],
            "segment_decisions": [{"segment_id": "segment_0", "direction": "forward", "weld_enabled": True}]}
    rough = tmp_path / ".cache/rough3d/20260930_010101_SAMPLE_1"
    native_data = {"schema_version": "welding-cot-v3", "planner_prompt_version": "offline-fixture-v1", "sample_id": "SAMPLE_1", "raw_instruction_ko": "native instruction",
                   "reference_sample_ids": ["REF_1"], "refined_task": {"status": "ready"}, "plan": plan,
                   "image_guidance_2d": guidance, "rough_trajectory_3d": reference}
    save(rough / "iteration_001/plan.json", native_data)
    save(rough / "query_image_guidance_2d.json", guidance)
    save(rough / "reference_trajectory_3d.json", reference)
    save(rough / "retrieval.json", {"query_sample_id": "SAMPLE_1", "results": [{"sample_id": "REF_1", "rough_action": {
        "segments": [{"points_start_relative_mm": reference["segments"][0]["points_xyz_mm"]}]}}]})
    save(rough / "refiner.json", {"status": "ready"})
    (rough / "query_masks.jpg").write_bytes(b"fixture query")
    for name in ("cot_ko.md", "vla_prompt.md", "image_guidance_2d_overlay.jpg", "rough_trajectory_3d.jpg", "review_all.jpg"):
        (rough / "iteration_001" / name).write_bytes(b"must never parse points from this file")
    # Unapproved extra native masks are deliberately available and must not enter the API.
    for camera in ("R", "S4"):
        mask.save(rough / "iteration_001" / f"{camera}_prediction.png")
    config = tmp_path / "inputs.json"
    save(config, {"dataset_root": str(tmp_path / "dataset"), "binding": str(binding_path),
                  "storage_root": str(storage), "rough_session": str(rough)})
    settings = GuidedVLASettings(inputs=config, attempts=tmp_path / ".cache/guided-vla", api_token="test-secret")
    return settings, guidance, plan, mask_path, rough, binding, job_path


def test_prepare_exact_points_direction_frame_approval_hash_and_unique_paths(inputs):
    settings, guidance, plan, mask, rough, _, _ = inputs
    client = GuidedVLAClient(settings)
    a, b = client.prepare(), client.prepare()
    assert a != b and a.parent == settings.attempts
    markdown = (a / "guidance.md").read_text(encoding="utf-8")
    points = [[float(x), float(y)] for x, y in re.findall(r"P\d+ = \(([^,]+), ([^)]+)\)", markdown)]
    assert points == guidance["segments"][0]["points_normalized"]
    assert "mask_normalized:F" in markdown and "forward" in markdown
    assert list((a / "masks").iterdir()) == [a / "masks/F_mask.png"]
    assert (a / "masks/F_mask.png").read_bytes() == mask.read_bytes()
    assert (a / "reference_trajectory_3d.json").read_bytes() == (rough / "reference_trajectory_3d.json").read_bytes()
    manifest = json.loads((a / "request_manifest.json").read_text(encoding="utf-8"))
    assert manifest["split"] == "train" and manifest["mask_views"] == ["F"]
    assert manifest["reference_in_request"] is False and manifest["approved_at"]
    assert "test-secret" not in (a / "request_manifest.json").read_text(encoding="utf-8")
    plan["segment_decisions"][0]["direction"] = "reverse"
    text, direction = serialize_guidance("SAMPLE_1", guidance, plan)
    assert direction == "reverse" and "`reverse`" in text
    assert [[float(x), float(y)] for x, y in re.findall(r"P\d+ = \(([^,]+), ([^)]+)\)", text)] == points


def test_transport_contract_response_export_and_single_submission(inputs):
    settings, *_ = inputs
    calls = []
    class Fake:
        def post(self, url, **kwargs):
            calls.append(kwargs)
            assert url == "http://127.0.0.1:8000/v1/predict-guided"
            assert kwargs["data"] == {"sample_id": "SAMPLE_1", "split": "train"}
            assert [name for name, _ in kwargs["files"]] == ["cot", "masks"]
            assert [spec[0] for _, spec in kwargs["files"]] == ["guidance.md", "F_mask.png"]
            assert b"registered_to_query" not in kwargs["files"][0][1][1].getvalue()
            assert kwargs["headers"] == {"X-API-Key": "test-secret"}
            r = response()
            r["task_metadata"] = {"coordinate_frame": "evil", "source_units": "evil", "episode_id": "evil", "api_token": "test-secret"}
            r["guidance"] = {"note": "test-secret"}
            r["cot_delivery"] = {"original_token_count": 100, "delivered_token_count": 100,
                                 "chunk_token_counts": [50, 50], "chunk_count": 2,
                                 "truncated": False, "access_token": "test-secret"}
            return r
    client = GuidedVLAClient(settings, transport=Fake())
    attempt = client.prepare()
    result = client.execute(attempt)
    assert isinstance(result, VLAPredictedTrajectory) and result.is_robot_executable is False
    metadata = json.loads((attempt / "metadata.json").read_text())
    assert metadata["coordinate_frame"] == response()["coordinate_frame"] and metadata["source_units"] == "mm"
    assert metadata["task_metadata"]["coordinate_frame"] == "evil" and metadata["episode_id"] == "SAMPLE_1"
    assert metadata["artifact_id"] == str(result.artifact_id)
    assert metadata["cot_delivery"]["original_token_count"] == 100
    assert metadata["cot_delivery"]["delivered_token_count"] == 100
    assert metadata["cot_delivery"]["chunk_token_counts"] == [50, 50]
    assert "access_token" not in metadata["cot_delivery"]
    assert "test-secret" not in (attempt / "metadata.json").read_text() + (attempt / "response.json").read_text()
    with np.load(attempt / "trajectory.npz", allow_pickle=False) as arrays:
        assert arrays["predicted_path_m"].shape == (9, 3)
        np.testing.assert_allclose(arrays["predicted_path_m"], np.array(response()["predicted_path_xyz_mm"]) * .001, atol=1e-7)
    with pytest.raises(GuidedVLAError, match="ALREADY_SUBMITTED"):
        client.execute(attempt)
    assert len(calls) == 1


@pytest.mark.parametrize("mutation", ["sample", "split", "shape", "width", "nan", "inf", "overflow", "metric", "frame", "none", "bool", "task"])
def test_response_rejection(mutation):
    r = response()
    if mutation == "sample": r["sample_id"] = "REFERENCE_1"
    if mutation == "split": r["split"] = "val"
    if mutation == "shape": r["predicted_path_xyz_mm"].pop()
    if mutation == "width": r["ground_truth_path_xyz_mm"][0].append(0)
    if mutation == "nan": r["predicted_path_xyz_mm"][0][0] = float("nan")
    if mutation == "inf": r["ground_truth_path_xyz_mm"][0][0] = float("inf")
    if mutation == "overflow": r["predicted_path_xyz_mm"][0][0] = 1e100
    if mutation == "metric": r["ade_mm"] = float("nan")
    if mutation == "frame": r["coordinate_frame"] = " "
    if mutation == "none": r["guidance_mode"] = "none"
    if mutation == "bool": r["predicted_path_xyz_mm"][0][0] = True
    if mutation == "task": r["task_metadata"] = []
    with pytest.raises(GuidedVLAError, match="RESPONSE_INVALID"):
        validate_response(r, "SAMPLE_1", "train")


def test_missing_guidance_mode_allowed_but_never_marked_executable():
    r = response(); r.pop("guidance_mode")
    assert validate_response(r, "SAMPLE_1", "train").guidance_mode is None


@pytest.mark.parametrize("mutation", [None, "truncated", "mismatch", "sum", "negative", "missing", "invalid_count"])
def test_observed_cot_delivery_contract_without_network(mutation):
    delivery = {"mode": "verbatim_full_cot_in_single_reference_view", "reference_view": "F",
                "original_cot_tokens": 328, "delivered_cot_tokens": 328,
                "chunk_token_counts": [0, 328, 0, 0, 0, 0, 0, 0, 0], "truncated": False}
    if mutation == "truncated": delivery["truncated"] = True
    if mutation == "mismatch": delivery["delivered_cot_tokens"] = 327
    if mutation == "sum": delivery["chunk_token_counts"][1] = 327
    if mutation == "negative": delivery["original_cot_tokens"] = delivery["delivered_cot_tokens"] = -1
    if mutation == "missing": delivery.pop("original_cot_tokens")
    if mutation == "invalid_count": delivery["chunk_count"] = 1
    r = response(); r["cot_delivery"] = delivery
    if mutation is None:
        result = validate_response(r, "SAMPLE_1", "train")
        assert result.cot_delivery == delivery
        stats = validate_cot_delivery(delivery)
        assert stats["view_chunk_slots_derived"] == 9 and stats["nonempty_chunks_derived"] == 1
        assert stats["chunk_count_field_present"] is False
    else:
        with pytest.raises(GuidedVLAError, match="COT_TRUNCATED|GUIDANCE_NOT_CONFIRMED"):
            validate_response(r, "SAMPLE_1", "train")


def test_full_float_precision_and_pixel_consistency(inputs):
    _, guidance, plan, *_ = inputs
    value = .12345678901234566
    guidance["segments"][0]["points_normalized"][0][0] = value
    guidance["segments"][0]["points_pixel"][0][0] = value * 100
    text, _ = serialize_guidance("SAMPLE_1", guidance, plan)
    assert float(re.search(r"P0 = \(([^,]+),", text)[1]) == value
    guidance["segments"][0]["points_pixel"][0][0] += 1
    with pytest.raises(GuidedVLAError): serialize_guidance("SAMPLE_1", guidance, plan)


@pytest.mark.parametrize("mutation", ["unapproved", "nonbinary", "rgb", "resolution", "guidance", "multiple", "split", "identity"])
def test_invalid_input_rejected_before_transport(inputs, mutation):
    settings, guidance, _, mask_path, rough, binding, job_path = inputs
    if mutation == "unapproved":
        job = json.loads(job_path.read_text()); job["mask"]["approved"] = False; save(job_path, job)
    if mutation == "nonbinary":
        with Image.open(mask_path) as mask: im = mask.copy()
        im.putpixel((1, 1), 128); im.save(mask_path)
    if mutation == "rgb":
        with Image.open(mask_path) as mask: mask.convert("RGB").save(mask_path)
    if mutation == "resolution": Image.new("L", (99, 100), 255).save(mask_path)
    if mutation in ("guidance", "multiple"):
        if mutation == "guidance": guidance["segments"][0]["points_normalized"][0][0] = .8
        else: guidance["segments"].append(guidance["segments"][0])
        native = json.loads((rough / "iteration_001/plan.json").read_text()); native["image_guidance_2d"] = guidance
        save(rough / "query_image_guidance_2d.json", guidance); save(rough / "iteration_001/plan.json", native)
    if mutation == "split":
        other = settings.inputs.parent / "dataset/2.데이터(NIA)/Validation/02.라벨링데이터/VL_Butt/03/SAMPLE_1/SAMPLE_1.json"
        save(other, {})
    if mutation == "identity":
        label = settings.inputs.parent / "dataset/2.데이터(NIA)/Training/02.라벨링데이터/TL_Butt/03/SAMPLE_1/SAMPLE_1.json"
        data = json.loads(label.read_text()); data["info"]["gid"] = "REFERENCE_1"; save(label, data)
    with pytest.raises(GuidedVLAError): GuidedVLAClient(settings).prepare()


@pytest.mark.parametrize("mutation", ["package", "approval", "native", "manifest", "reference_flag", "provenance"])
def test_stale_or_tampered_attempt_never_sent(inputs, mutation):
    settings, _, _, _, rough, _, job_path = inputs
    client = GuidedVLAClient(settings, transport=type("Never", (), {"post": lambda *a, **kw: pytest.fail("must not send")})())
    attempt = client.prepare()
    if mutation == "package": (attempt / "guidance.md").write_text("changed")
    if mutation == "approval":
        data = json.loads(job_path.read_text()); data["mask"]["approved"] = False; save(job_path, data)
    if mutation == "native": (rough / "reference_trajectory_3d.json").write_text("changed")
    if mutation == "manifest":
        data = json.loads((attempt / "request_manifest.json").read_text(encoding="utf-8")); data["sample_id"] = "REF_1"; save(attempt / "request_manifest.json", data)
    if mutation in ("reference_flag", "provenance"):
        data = json.loads((attempt / "request_manifest.json").read_text(encoding="utf-8"))
        if mutation == "reference_flag": data["reference_registered_to_query"] = True
        else: data["mask_source"] = "vlm_segment"
        save(attempt / "request_manifest.json", data)
    with pytest.raises(GuidedVLAError): client.execute(attempt)
    assert not (attempt / "submission.json").exists()


def test_live_disabled_and_failed_response_is_not_retried(inputs):
    settings, *_ = inputs
    client = GuidedVLAClient(settings)
    attempt = client.prepare()
    with pytest.raises(GuidedVLAError, match="LIVE_DISABLED"): client.execute(attempt)
    calls = []
    class Fake:
        def post(self, *args, **kwargs):
            calls.append(1); r = response(); r["sample_id"] = "wrong"; return r
    client = GuidedVLAClient(settings, transport=Fake())
    with pytest.raises(GuidedVLAError, match="RESPONSE_INVALID"): client.execute(attempt)
    with pytest.raises(GuidedVLAError, match="ALREADY_SUBMITTED"): client.execute(attempt)
    assert len(calls) == 1 and not (attempt / "completion.json").exists()


def test_native_rough3d_fake_process_and_reference_type_separation(inputs, monkeypatch):
    settings, _, _, _, rough, _, _ = inputs
    repo = settings.inputs.parent / "repo"; repo.mkdir(); (repo / "cot.py").write_text("# fixture")
    config = settings.inputs.parent / "native.yaml"
    config.write_text(yaml.safe_dump({"data": {"root": str(settings.inputs.parent / "dataset")},
                                    "output": {"root": str(rough.parent)}, "models": {"planner": "fixture"}}))
    # A fresh output is produced only by this fake process, never by native inference.
    original = rough.rename(rough.with_name("saved_fixture"))
    session = settings.inputs.parent / ".cache/approved/session"
    save(session / "status.json", {"status": "ok", "accepted_iteration": 1})
    save(session / "iteration_001/result.json", {"sample_id": "SAMPLE_1"})
    def fake(command, **kwargs):
        assert kwargs["cwd"] == repo and "--once" in command and command[-1] == str(session)
        original.rename(rough)
        return 0, [str(rough / "iteration_001/review_all.jpg")]
    runtime = NativeRuntime(ModelSettings(stage="rough3d", backend="native", repository=repo,
                            python=Path(sys.executable), native_config=config), records=settings.inputs.parent / ".cache/records", run=fake)
    result = NativeRough3DClient(runtime).run_session(session, "native instruction")
    assert isinstance(result.reference_trajectory_3d, ReferenceTrajectory3D)
    assert not isinstance(result.reference_trajectory_3d, VLAPredictedTrajectory)
    assert result.reference_trajectory_3d.registered_to_query is False
    assert result.reference_trajectory_3d.is_robot_executable is False
    assert NativeRough2DClient.__name__ == "NativeRoughClient"


def test_backend_settings_only_and_credentials_hidden(inputs):
    settings, *_ = inputs
    assert "test-secret" not in repr(settings)
    for url in ("http://user:secret@localhost", "http://localhost/v1/other", "file:///tmp", "http://localhost?token=x"):
        with pytest.raises(GuidedVLAError): GuidedVLAClient(replace(settings, server_url=url))


def test_actual_multipart_serializer_with_mock_http_only(inputs, monkeypatch):
    """Exercise HTTP serialization without sockets, external servers or inference."""
    from email.parser import BytesParser
    settings, *_ = inputs
    client = GuidedVLAClient(settings)
    attempt = client.prepare()
    _, package = client.verify(attempt)
    original = httpx.Client
    captured = []
    def handler(request):
        captured.append(request)
        assert request.method == "POST" and request.url.path == "/v1/predict-guided"
        raw = ("Content-Type: " + request.headers["content-type"] + "\r\nMIME-Version: 1.0\r\n\r\n").encode() + request.content
        parts = BytesParser().parsebytes(raw).get_payload()
        assert [p.get_param("name", header="content-disposition") for p in parts] == ["sample_id", "split", "cot", "masks"]
        assert parts[0].get_payload(decode=True) == b"SAMPLE_1" and parts[1].get_payload(decode=True) == b"train"
        assert parts[2].get_payload(decode=True) == package["guidance.md"]
        assert parts[3].get_payload(decode=True) == package["masks/F_mask.png"]
        return httpx.Response(200, json=response())
    monkeypatch.setattr("backend.model_clients.guided_vla.httpx.Client",
                        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises(GuidedVLAError, match="LIVE_DISABLED"):
        GuidedVLAClient(settings, transport=HTTPGuidedTransport()).execute(attempt)
    # --live is exercised against an in-memory MockTransport, never a network service.
    result = GuidedVLAClient(settings, transport=HTTPGuidedTransport()).execute(attempt, live=True)
    assert result.sample_id == "SAMPLE_1" and len(captured) == 1
