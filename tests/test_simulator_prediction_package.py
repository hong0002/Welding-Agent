"""Offline fixtures/stub processes only: no model API, external pipeline or Isaac."""
import json
from pathlib import Path
import sys
from uuid import uuid4

from fastapi.testclient import TestClient
import h5py
import numpy as np
import pytest

from backend.main import create_app
from backend.model_clients.trajectory_contracts import VLAPredictedTrajectory
from backend.orchestrator.state_machine import WorkflowError
from backend.services.simulator_client import LocalSimulatorClient, SimulatorConfig
from backend.services.simulator_package_gate import verify_current_package
from backend.services.simulator_prediction_package import (
    CurrentVLASimulatorService, PackageSettings, SIMULATOR_FILES, SimulatorPredictionAdapter,
    query_assets, read, sha, write,
)
from tests.test_simulator import FakeLauncher, REQUEST_ID, ready


class FakeFixtures:
    def inspect(self, root, h5, obj, sample_id):
        return dict(sample_id=sample_id, ready=sample_id.startswith(("L_PR_", "T_PP_", "T_PR_")),
                    supported_families=["L_PR_", "T_PP_", "T_PR_"])


def fixture(tmp_path, sample="B_PR_03_0001"):
    project = tmp_path / "project"
    attempt = project / ".cache/native-models/guided-vla" / str(uuid4())
    attempt.mkdir(parents=True)
    simulator = tmp_path / "simulator"
    for name in SIMULATOR_FILES:
        file = simulator / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("# fake external contract", encoding="utf-8")
    (simulator / "rbpodo_description/robots/rb10_1300e_u.urdf").write_text('<robot name="fake"/>')
    data = tmp_path / "dataset"
    h5, obj = query_assets(data, sample)
    h5.parent.mkdir(parents=True)
    obj.parent.mkdir(parents=True)
    obj.write_text("# synthetic exact sample CAD\nv 0 0 0\nv 10 0 0\nv 0 10 0\nf 1 2 3\n")
    xyz = np.column_stack([np.linspace(710, 740, 150), np.linspace(25, 20, 150), np.linspace(310, 250, 150)])
    with h5py.File(h5, "w") as handle:
        handle["trajectory"] = np.column_stack([xyz, np.zeros_like(xyz)])
    gt = np.column_stack([np.interp(np.linspace(0,149,9), np.arange(150), xyz[:,j]) for j in range(3)])
    result = VLAPredictedTrajectory(sample_id=sample, split="train", coordinate_frame="source_robot_frame_unaligned_with_isaac",
        predicted_path_xyz_mm=(gt+np.array([80,40,0])).tolist(), ground_truth_path_xyz_mm=gt.tolist(),
        ade_mm=97.15410614013672, fde_mm=155.03475952148438, task_metadata={},
        input_sources={"start_xyz":"ground_truth_h5_first_point"})
    write(attempt / "response.json", result.model_dump(mode="json"))
    np.savez(attempt / "trajectory.npz", predicted_path_m=np.asarray(result.predicted_path_xyz_mm,dtype=np.float32)*np.float32(.001),
             ground_truth_path_m=np.asarray(result.ground_truth_path_xyz_mm,dtype=np.float32)*np.float32(.001))
    write(attempt / "metadata.json", dict(episode_id=sample, split="train", artifact_id=str(result.artifact_id),
          artifact_type="VLAPredictedTrajectory", attempt_id=attempt.name, source_units="mm", scale_to_meters=.001,
          coordinate_frame=result.coordinate_frame, is_robot_executable=False))
    write(attempt / "reference_trajectory_3d.json", {"source_sample_id":"L_PR_09_9999", "registered_to_query":False})
    job, mask = project / "job.json", project / "mask.png"
    job.write_text('{"mask":"approved"}'); mask.write_bytes(b"binary mask fixture")
    write(attempt / "request_manifest.json", dict(attempt_id=attempt.name, sample_id=sample, split="train",
        source_job=str(job), source_job_sha256=sha(job), source_mask=str(mask), source_mask_sha256=sha(mask),
        source_mask_id=str(uuid4()), approved_at="2026-09-30T06:35:10+00:00", reference_in_request=False,
        files={"reference_trajectory_3d.json":sha(attempt / "reference_trajectory_3d.json")}))
    complete(attempt)
    settings = PackageSettings(attempt.parent, data, simulator, project / ".cache/simulator/prediction-packages", project=project)
    adapter = SimulatorPredictionAdapter(settings, fixtures=FakeFixtures())
    return adapter, result, attempt, h5


def complete(attempt):
    path = attempt / "completion.json"
    path.write_text(json.dumps(dict(attempt_id=attempt.name, response_validated=True,
          files={name:sha(attempt/name) for name in ("response.json","trajectory.npz","metadata.json")})))


def test_b_pr_byte_copy_contract_metrics_and_fixture_blocker(tmp_path):
    adapter, result, attempt, _ = fixture(tmp_path)
    before = {f.name:sha(f) for f in attempt.iterdir() if f.is_file()}
    package = adapter.prepare(result.artifact_id)
    assert package.preflight["verdict"] == "B_PR_FIXTURE_SUPPORT_REQUIRED"
    assert package.preflight["package_contract"] == "PASS" and not package.preflight["fixture_ready"]
    assert package.preflight["gt_h5_frame_error_mm_max"] < .05
    episode = package.prediction_root / result.sample_id
    assert (episode / "trajectory.npz").read_bytes() == (attempt / "trajectory.npz").read_bytes()
    assert read(episode / "metadata.json") == dict(episode_id=result.sample_id, coordinate_frame=result.coordinate_frame,
                                                  source_units="mm", scale_to_meters=.001)
    assert package.sample_id != read(attempt / "reference_trajectory_3d.json")["source_sample_id"]
    assert package.ade_mm == result.ade_mm and package.fde_mm == result.fde_mm
    assert package.simulation_only and not package.physical_robot_executable and not package.is_robot_executable
    assert "not VLA" in package.orientation_source and package.point_count == 9
    assert before == {f.name:sha(f) for f in attempt.iterdir() if f.is_file()}
    assert "directory" not in package.summary() and "points" not in json.dumps(package.summary())
    adapter.verify(package)


@pytest.mark.parametrize("sample", ["L_PR_03_0002", "T_PP_03_0001", "T_PR_03_0001"])
def test_supported_families_keep_nine_points_with_fake_fixture(tmp_path, sample):
    adapter, result, attempt, _ = fixture(tmp_path, sample)
    package = adapter.prepare(result.artifact_id)
    assert package.preflight["verdict"] == "GUIDED_VLA_SIMULATOR_OFFLINE_READY"
    with np.load(package.prediction_root / sample / "trajectory.npz") as arrays:
        assert arrays["predicted_path_m"].shape == (9,3)
    assert (attempt/"trajectory.npz").read_bytes() == (package.prediction_root/sample/"trajectory.npz").read_bytes()


@pytest.mark.parametrize("change", ["hash", "frame", "identity", "shape", "predicted", "gt", "job", "mask", "obj", "duplicate", "unknown"])
def test_invalid_changed_or_ambiguous_sources_fail_closed(tmp_path, change):
    adapter, result, attempt, h5 = fixture(tmp_path)
    if change == "hash": (attempt/"trajectory.npz").write_bytes(b"changed")
    elif change in {"frame", "identity"}:
        response=read(attempt/"response.json")
        response["coordinate_frame" if change=="frame" else "sample_id"] = "start_relative" if change=="frame" else "B_PR_03_0002"
        (attempt/"response.json").write_text(json.dumps(response)); complete(attempt)
    elif change in {"shape", "predicted"}:
        with np.load(attempt/"trajectory.npz") as a: gt=a["ground_truth_path_m"].copy(); pred=a["predicted_path_m"].copy()
        if change == "shape": pred=pred[:8]
        else: pred[2,0] += .001
        np.savez(attempt/"trajectory.npz", predicted_path_m=pred, ground_truth_path_m=gt); complete(attempt)
    elif change == "gt":
        with h5py.File(h5,"r+") as handle:
            value=handle["trajectory"][:]; value[:,:3] += 1; handle["trajectory"][:]=value
    elif change in {"job", "mask"}: (adapter.settings.project/("job.json" if change=="job" else "mask.png")).write_bytes(b"changed")
    elif change == "obj": query_assets(adapter.settings.dataset_root,result.sample_id)[1].unlink()
    elif change == "duplicate":
        duplicate=attempt.parent/str(uuid4()); duplicate.mkdir(); write(duplicate/"metadata.json",read(attempt/"metadata.json"))
    elif change == "unknown": result=result.model_copy(update={"artifact_id":uuid4()})
    with pytest.raises(WorkflowError): adapter.prepare(result.artifact_id)


def test_package_tamper_rejected_at_readmission(tmp_path):
    adapter, result, _, _ = fixture(tmp_path)
    package=adapter.prepare(result.artifact_id)
    (package.prediction_root/package.sample_id/"trajectory.npz").write_bytes(b"changed")
    with pytest.raises(ValueError): adapter.verify(package)


def test_uuid_only_api_b_pr_never_calls_simulator(tmp_path):
    adapter, result, _, _ = fixture(tmp_path)
    class NeverSim:
        calls=[]
        def run_current_vla_prediction(self, package): self.calls.append(package); raise AssertionError("must not run")
        def close(self): pass
    simulator=NeverSim()
    service=CurrentVLASimulatorService(simulator,adapter=adapter)
    with TestClient(create_app(tmp_path/"storage", simulator=simulator, current_vla_simulator=service)) as client:
        body={"artifact_id":str(result.artifact_id)}
        response=client.post("/api/simulator/current-vla/preflight",json=body)
        assert response.status_code == 200 and response.json()["preflight"]["verdict"] == "B_PR_FIXTURE_SUPPORT_REQUIRED"
        assert client.post("/api/simulator/run-current-vla",json=body).status_code == 409
        assert not simulator.calls
        assert client.post("/api/simulator/run-current-vla",json={**body,"path":"D:/arbitrary.npz"}).status_code == 422
        assert client.post("/api/simulator/run-current-vla",json={"artifact_id":"../escape"}).status_code == 422
        assert client.post("/api/simulator/current-vla/preflight?path=x",json=body).status_code == 400
        assert client.post("/api/simulator/run-current-vla",json=body,headers={"Origin":"https://untrusted.example"}).status_code == 403


def test_current_sample_uses_uuid_package_without_configured_sample_fallback(tmp_path):
    adapter, result, _, _ = fixture(tmp_path,"L_PR_03_0002")
    config=SimulatorConfig(adapter.settings.simulator_root,Path(sys.executable),"L_PR_03_0001",
                           adapter.settings.dataset_root,tmp_path/"old_predictions",tmp_path/"runtime")
    bridge=LocalSimulatorClient(config,launcher=FakeLauncher(),monitor=False)
    service=CurrentVLASimulatorService(bridge,adapter=adapter)
    try:
        with pytest.raises(WorkflowError,match="must be READY"): service.run_current_vla_prediction(result.artifact_id)
        assert not bridge.launcher.calls
        ready(bridge)
        state=service.run_current_vla_prediction(result.artifact_id)
        assert state["latest_sample"]["artifact_id"] == str(result.artifact_id)
        assert state["sample_id"] == "L_PR_03_0001"  # configured replay stays separate
        args=bridge.launcher.calls[-1][3]
        assert args[args.index("--sample")+1] == "L_PR_03_0002"
        claim=bridge.launcher.options[-1]["current_prediction"]
        verify_current_package(claim,config.root,args,project=adapter.settings.project)
        bridge._consume_line("sample",bridge.sample,f"[QUEUED] {REQUEST_ID} (queued, not yet confirmed as played)")
        bridge.sample.code=0
        assert bridge.readers_done["sample"].wait(2)
        output=bridge.session_dir/"outputs"/result.sample_id/"vla_prediction/requests/unique/scene.usda"
        output.parent.mkdir(parents=True)
        for file in (output,output.with_suffix(".actual_weld.npz"),output.parent/"trajectory_solution.npz"): file.write_bytes(b"fixture")
        write(output.parent/"report.json", dict(sample_id=result.sample_id,trajectory_source="vla_prediction",point_count=9,
            tracking_point="mounted_fixture_v2",source_h5=bridge.latest_sample["source_h5"],
            prediction=dict(source_directory=bridge.latest_sample["prediction_directory"],position_source="VLA predicted_path_m")))
        response=bridge.session_dir/"queue/results"/f"{REQUEST_ID}.json"; response.parent.mkdir(parents=True)
        write(response,dict(id=REQUEST_ID,sample=result.sample_id,state="done",playback_mode="model_predict",output=str(output)))
        assert bridge.status()["latest_sample"]["status"] == "SUCCEEDED"
        package_path=Path(claim["package"]); package_path.write_bytes(b"changed")
        with pytest.raises(ValueError,match="changed"): verify_current_package(claim,config.root,args,project=adapter.settings.project)
    finally: bridge.close()
