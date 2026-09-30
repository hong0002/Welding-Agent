"""Native boundaries with tiny owned fixtures only; no SDK/SSH/Isaac/dataset scan."""
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw
import pytest
import yaml

from backend.model_clients.config import ModelSettings
from backend.model_clients.contracts import ModelFault
from backend.model_clients.native import NativeRuntime, NativeSegmentClient, NativeRoughClient, read_native_result
from backend.model_clients.native_preview import to_preview
from backend.model_clients.native_process import run_native
from backend.native_models import compare
from backend.schemas import StructuredInstruction
from backend.services.components import detect_components


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def native(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.model_clients.native.ROOT", tmp_path)
    repo = tmp_path / "native project"
    repo.mkdir()
    for name in ("mask.py", "cot.py"):
        (repo / name).write_text("# stub", encoding="utf-8")
    image = repo / "data/2.데이터(NIA)/Validation/01.원천데이터/SAMPLE_1/SAMPLE_1_F_Color.png"
    image.parent.mkdir(parents=True)
    Image.new("RGB", (100, 100), "gray").save(image)
    config = {"mask": {"dataset_root": "data/2.데이터(NIA)", "output_dir": "outputs/masks", "model": "stub"},
              "data": {"root": "data"}, "output": {"root": "outputs/rough"}, "models": {"planner": "stub"}}
    config_path = repo / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    binding = tmp_path / "binding.json"
    save(binding, {"sample_id": "SAMPLE_1", "camera": "F", "image": str(image)})
    return ModelSettings(stage="segment", backend="native", repository=repo, python=Path(sys.executable),
                         native_config=config_path, native_binding=binding, reference_mode="none")


def segment_output(root, instruction="native exact text", name="20260930_010101_SAMPLE_1"):
    directory = root / name
    iteration = directory / "iteration_001"
    save(directory / "retrieval.json", {"query_sample_id": "SAMPLE_1", "results": [{"sample_id": "REF_1"}]})
    paths = [[(10, 20), (40, 20)], [(60, 70), (90, 70)]]
    predictions = {"F": {"camera_id": "F", "polylines": [{"points": [{"x": x, "y": y} for x, y in path]} for path in paths]}}
    save(iteration / "result.json", {"sample_id": "SAMPLE_1", "instruction": instruction, "prompt_version": "stub-v1",
                                    "predictions": predictions, "retrieved_sample_ids": ["REF_1"]})
    mask = Image.new("L", (100, 100)); draw = ImageDraw.Draw(mask)
    for path in paths:
        draw.line(path, fill=255, width=7)
    mask.save(iteration / "F_prediction.png")
    mask.save(iteration / "F_gt.png")
    for name in ("F_comparison.jpg", "comparison_all.jpg"):
        mask.convert("RGB").save(iteration / name)
    return directory, mask


def rough_data():
    from tests.test_model_clients import rough_output
    data = json.loads(json.dumps(rough_output()).replace("web", "F"))
    data["rough_trajectory"] = data.pop("rough_action")
    data.update(schema_version="welding-cot-v2", sample_id="SAMPLE_1", raw_instruction_ko="native exact text",
                reference_sample_ids=["REF_1"], planner_prompt_version="stub-v1", refiner_prompt_version="stub-v1")
    return data


def rough_output(root):
    directory = root / "20260930_010102_SAMPLE_1"
    data = rough_data()
    save(directory / "retrieval.json", {"query_sample_id": "SAMPLE_1", "results": [{"sample_id": "REF_1"}]})
    save(directory / "refiner.json", data["refined_task"])
    save(directory / "query_rough_action.json", data["rough_trajectory"])
    save(directory / "iteration_001/plan.json", data)
    for name in ("cot_ko.md", "vla_prompt.md", "rough_trajectory_overlay.jpg"):
        (directory / "iteration_001" / name).write_bytes(b"native exact artifact\n")
    (directory / "query_masks.jpg").write_bytes(b"native query")
    return directory


def test_native_cli_cwd_args_native_paths_and_byte_preservation(native, tmp_path):
    seen = []
    def run(command, **kwargs):
        seen.append(command)
        assert command[:4] == [str(native.python), "-B", "-u", str(native.repository / "mask.py")]
        assert command[-2:] == ["--sample-id", "SAMPLE_1"]  # native default view selection
        assert "--instruction=native exact text" in command
        assert kwargs == {"cwd": native.repository, "timeout": native.timeout}
        directory, _ = segment_output(native.repository / "outputs/masks")
        return 0, [str(directory / "iteration_001/comparison_all.jpg")]
    runtime = NativeRuntime(native, records=tmp_path / "records", run=run)
    assert runtime.status()["reference_mode"] == "native"
    assert runtime.status()["state"] == "UNVERIFIED" and not seen
    image = Image.new("RGB", (100, 100), "gray")
    result = NativeSegmentClient(runtime).segment(image, instruction="native exact text")
    assert result.info["model_provenance"].reference_mode == "native" and runtime.status()["ready"]
    assert len(seen) == 1
    record = json.loads(next((tmp_path / "records").glob("*.json")).read_text(encoding="utf-8"))
    assert Path(record["directory"]).parent == native.repository / "outputs/masks"
    assert not list((tmp_path / "records").rglob("*.png"))
    assert not (Path(record["directory"]) / "status.json").exists()  # --once is not approval


def test_identity_mismatch_and_unapproved_mask_do_not_launch(native, tmp_path):
    def fail(*args, **kwargs):
        pytest.fail("Native model must not run")
    segment = NativeSegmentClient(NativeRuntime(native, records=tmp_path / "records", run=fail))
    with pytest.raises(ModelFault) as exc:
        segment.segment(Image.new("RGB", (100, 100), "black"))
    assert exc.value.code == "NATIVE_INPUT_MISMATCH"
    rough = NativeRoughClient(NativeRuntime(replace(native, stage="rough"), run=fail))
    with pytest.raises(ModelFault) as exc:
        rough.predict(Image.new("RGB", (100, 100), "gray"), None, None, None, language="text")
    assert exc.value.code == "NATIVE_MASK_NOT_APPROVED"


def make_workflow(native, tmp_path):
    from backend.orchestrator.workflow import Workflow
    from backend.services.storage import LocalStorage
    def segment(command, **kwargs):
        directory, _ = segment_output(native.repository / "outputs/masks")
        return 0, [str(directory / "iteration_001/comparison_all.jpg")]
    def rough(command, **kwargs):
        session = Path(command[-1])
        assert session.parent == tmp_path / "records/approved"
        assert not (native.repository / "outputs/masks/20260930_010101_SAMPLE_1/status.json").exists()
        assert "--instruction=native exact text" in command
        directory = rough_output(native.repository / "outputs/rough")
        return 0, [str(directory / "iteration_001/rough_trajectory_overlay.jpg")]
    return Workflow(LocalStorage(tmp_path / "storage"),
        segmentation=NativeSegmentClient(NativeRuntime(native, records=tmp_path / "records", run=segment)),
        rough=NativeRoughClient(NativeRuntime(replace(native, stage="rough"), records=tmp_path / "records", run=rough)))


def automatic_job(workflow, native):
    image = json.loads(native.native_binding.read_text())["image"]
    job = workflow.upload_scene(Path(image).read_bytes())
    return workflow.set_mask(job.id, instruction="native exact text")


def test_rough_uses_current_human_approved_session_and_stops_before_vla(native, tmp_path):
    workflow = make_workflow(native, tmp_path)
    job = automatic_job(workflow, native)
    assert job.mask.mask_source == "vlm_segment" and not job.mask.approved
    from backend.orchestrator.state_machine import WorkflowError
    with pytest.raises(WorkflowError):
        workflow.apply_instruction(job.id, "native exact text", StructuredInstruction(direction="left_to_right"))
    job = workflow.approve_mask(job.id, job.mask.id)
    assert job.mask.approved and job.mask.approved_at
    workflow.apply_instruction(job.id, "native exact text", StructuredInstruction(direction="left_to_right"))
    job = workflow.plan(job.id)
    result = job.rough_trajectory
    assert [s.region_id for s in result.segments] == [0, 1]
    assert result.segments[0].points[-1].x == 40 and result.segments[1].points[0].x == 60
    assert result.artifact.provenance.approved_mask_session_id
    assert result.artifact.provenance.native_artifacts["iteration_001/cot_ko.md"]
    assert job.final_trajectory is None and job.state.value == "ROUGH_PATH_READY"
    from backend.agent.context import workspace_summary
    summary = workspace_summary(job)["rough_summary"]
    assert summary["segment_count"] == 2 and summary["point_count"] == sum(len(s.points) for s in result.segments)
    assert summary["cot_ko_available"] and summary["vla_prompt_available"]
    assert summary["frame"] == "image_top_left_x_right_y_down" and summary["units"] == "px"
    assert "native exact artifact" not in json.dumps(summary) and "points" not in summary
    with pytest.raises(ModelFault, match="Rough"):
        workflow.refine(job.id)


def test_edited_binary_clips_native_vectors_without_model_and_seals_input(native, tmp_path):
    from io import BytesIO
    from backend.model_clients.native_approval import pixel_hash
    workflow = make_workflow(native, tmp_path)
    job = automatic_job(workflow, native)
    original_mask_id = job.mask.id
    mask = workflow.storage.read_image("masks", job.mask.id)
    ImageDraw.Draw(mask).rectangle((0, 0, 19, 40), fill=0)
    buf = BytesIO(); mask.save(buf, format="PNG")
    job = workflow.set_mask(job.id, buf.getvalue(), edited_from_mask_id=original_mask_id)
    assert job.mask.mask_source == "manual_edited" and job.mask.approved
    image, mask, components = workflow._conditioning(job)
    session, accepted, proof = workflow.rough.prepare_session(image, mask, components)
    assert list(accepted["predictions"]) == ["F"]
    assert accepted["predictions"]["F"]["polylines"][0]["points"][0]["x"] >= 19.5
    assert proof["mask_pixels_sha256"] == pixel_hash(mask) and proof["mask_id"] == str(job.mask.id)
    assert proof["source_native_artifact_id"] == str(job.mask.artifact.provenance.native_source_artifact_id)
    assert set(str(p.relative_to(session)) for p in session.rglob("*") if p.is_file()) == {
        "status.json", str(Path("iteration_001/result.json"))}
    workflow.rough.approvals.verify(session, mask, job.mask)
    (session / "status.json").write_text('{}')
    with pytest.raises(ModelFault):
        workflow.rough.approvals.verify(session, mask, job.mask)
    # A subsequent brush addition has no native centerline: reject before run_session.
    ImageDraw.Draw(mask).rectangle((0, 0, 8, 8), fill=255)
    with pytest.raises(ModelFault) as error:
        workflow.rough.prepare_session(image, mask, detect_components(mask))
    assert error.value.code == "NATIVE_MASK_EDIT_UNSUPPORTED"


def test_unapproved_stale_and_raw_api_confirmation_boundaries(native, tmp_path):
    from uuid import uuid4
    from backend.orchestrator.state_machine import WorkflowError
    workflow = make_workflow(native, tmp_path)
    job = automatic_job(workflow, native)
    with pytest.raises(WorkflowError):
        workflow.approve_mask(job.id, uuid4())
    mask = workflow.storage.read_image("masks", job.mask.id)
    mask.info["mask_artifact"] = job.mask
    with pytest.raises(ModelFault) as error:
        workflow.rough.prepare_session(Image.new("RGB", mask.size, "gray"), mask, detect_components(mask))
    assert error.value.code == "NATIVE_MASK_NOT_APPROVED"
    from backend.agent.context import workspace_summary
    assert workspace_summary(job)["mask_approval_required"]
    assert "cot_ko" not in str(workspace_summary(job))


def test_clipping_splits_disconnected_regions_and_preserves_brush_restoration(native, tmp_path):
    from backend.model_clients.native_approval import clipped_predictions
    session, original = segment_output(tmp_path / "source")
    prediction = json.loads((session / "iteration_001/result.json").read_text())["predictions"]["F"]
    edited = original.copy()
    ImageDraw.Draw(edited).rectangle((23, 10, 27, 30), fill=0)
    result = clipped_predictions(prediction, original, edited, detect_components(edited))
    assert len(result["polylines"]) == 3
    assert result["polylines"][0]["points"][-1]["x"] < 23
    assert result["polylines"][1]["points"][0]["x"] > 27
    restored = clipped_predictions(prediction, original, original.copy(), detect_components(original))
    assert restored == prediction


def test_native_output_outside_workspace_rejected_before_process(native, tmp_path):
    config = yaml.safe_load(native.native_config.read_text(encoding="utf-8"))
    config["mask"]["output_dir"] = str(tmp_path.parent / "outside-workspace")
    native.native_config.write_text(yaml.safe_dump(config), encoding="utf-8")
    runtime = NativeRuntime(native, records=tmp_path / "records", run=lambda *a, **kw: pytest.fail("must not launch"))
    with pytest.raises(ModelFault) as error:
        runtime.execute(sample_id="SAMPLE_1", instruction="text")
    assert error.value.code == "MODEL_NOT_CONFIGURED"


def test_native_timeout_retains_parity_budget_and_experimental_stays_bounded(monkeypatch):
    monkeypatch.setenv("WELD_SEGMENT_BACKEND", "native")
    monkeypatch.setenv("WELD_SEGMENT_TIMEOUT", "900")
    assert ModelSettings.from_env("segment").timeout == 900
    monkeypatch.setenv("WELD_SEGMENT_BACKEND", "experimental")
    assert ModelSettings.from_env("segment").timeout == 120


@pytest.mark.parametrize("mutation", ["bridge", "normalized", "region_order", "direction", "duplicate", "camera", "skip", "travel"])
def test_native_preview_rejects_incompatible_model_result(native, tmp_path, mutation):
    session, mask = segment_output(tmp_path / "approved")
    accepted = json.loads((session / "iteration_001/result.json").read_text())
    data = rough_data()
    if mutation == "bridge": data["rough_trajectory"]["segments"][0]["connected_to_next"] = True
    if mutation == "normalized": data["rough_trajectory"]["segments"][0]["points_normalized"][0][0] = 99
    if mutation == "region_order": data["plan"]["operations"][0]["order"] = 9
    if mutation == "direction": data["plan"]["segment_decisions"][0]["direction"] = "reverse"
    if mutation == "duplicate": data["rough_trajectory"]["segments"][1]["source_mask_id"] = "F:polyline_0"
    if mutation == "camera": data["rough_trajectory"]["primary_camera"] = "R"
    if mutation == "skip": data["plan"]["segment_decisions"][0]["weld_enabled"] = False
    if mutation == "travel": data["plan"]["operations"].append({"action": "approach", "order": 3, "segment_id": "segment_1", "weld_enabled": True})
    with pytest.raises(ValueError):
        to_preview(data, accepted, "F", mask.size, StructuredInstruction(direction="left_to_right", region_order=[0, 1]), detect_components(mask))


def test_exit_zero_without_artifacts_and_timeout_are_not_success(native, tmp_path):
    for run, expected in ((lambda *a, **kw: (0, []), "NATIVE_RESULT_INCOMPLETE"),
                         (lambda *a, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired("stub", 1)), "MODEL_TIMEOUT")):
        runtime = NativeRuntime(native, records=tmp_path / "records", run=run)
        with pytest.raises(ModelFault) as exc:
            runtime.execute(sample_id="SAMPLE_1", instruction="text")
        assert exc.value.code == expected and not runtime.status()["ready"]


def test_stale_output_never_accepted(native, tmp_path):
    directory, _ = segment_output(native.repository / "outputs/masks")
    runtime = NativeRuntime(native, records=tmp_path / "records",
                            run=lambda *a, **kw: (0, [str(directory / "iteration_001/comparison_all.jpg")]))
    with pytest.raises(ModelFault) as exc:
        runtime.execute(sample_id="SAMPLE_1", instruction="native exact text")
    assert exc.value.code == "NATIVE_RESULT_INCOMPLETE"


def test_saved_comparison_detects_mask_and_markdown_changes(tmp_path):
    a, _ = segment_output(tmp_path / "A")
    b, _ = segment_output(tmp_path / "B")
    assert compare("segment", a, b)["all_equal"]
    Image.new("L", (100, 100)).save(b / "iteration_001/F_prediction.png")
    assert not compare("segment", a, b)["checks"]["masks"]
    a, b = rough_output(tmp_path / "C"), rough_output(tmp_path / "D")
    assert compare("rough", a, b)["all_equal"]
    (b / "iteration_001/cot_ko.md").write_text("changed")
    assert not compare("rough", a, b)["checks"]["markdown"]
    (b / "iteration_001/vla_prompt.md").unlink()
    with pytest.raises(ModelFault):
        read_native_result("rough", b, "SAMPLE_1", "native exact text")


def test_real_alias_selects_native_and_dummy_stays_dummy(monkeypatch, native):
    from backend.model_clients.factory import configured_clients
    from backend.services.segmentation_client import DummySegmentationClient
    monkeypatch.setattr(ModelSettings, "from_env", lambda stage: replace(native, stage=stage, backend="real"))
    a, b = configured_clients()
    assert isinstance(a, NativeSegmentClient) and isinstance(b, NativeRoughClient)
    monkeypatch.setattr(ModelSettings, "from_env", lambda stage: replace(native, stage=stage, backend="dummy"))
    assert isinstance(configured_clients()[0], DummySegmentationClient)


def test_real_process_gate_preserves_cwd_and_literal_arguments(tmp_path):
    script = tmp_path / "tiny stub.py"
    script.write_text("import os,sys\nassert os.getcwd()==sys.argv[1]\nassert sys.argv[2]=='literal & $value ; text'\nprint('[VIEW] '+sys.argv[1]+'/result.jpg',flush=True)\n", encoding="utf-8")
    code, views = run_native([sys.executable, "-B", str(script), str(tmp_path), "literal & $value ; text"], cwd=tmp_path, timeout=5)
    assert code == 0 and len(views) == 1
