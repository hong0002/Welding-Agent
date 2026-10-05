"""Completed Guided VLA -> unchanged simulator export. No inference or Isaac imports.

The UUID boundary resolves only backend-owned completed attempts. Geometry readiness
is separate from NPZ/frame compatibility; unsupported fixtures fail closed.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Literal, Protocol
from uuid import UUID, uuid4
import xml.etree.ElementTree as ET

from backend.services.environment import backend_env_values
from backend.services.dataset_sample import exact_assets
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.model_clients.trajectory_contracts import VLAPredictedTrajectory
from backend.model_clients.native import NATIVE_PYTHON
from backend.orchestrator.state_machine import WorkflowError
from backend.services.legacy_prediction_adapter import inspect_legacy_prediction, metadata_for

PROJECT = Path(__file__).resolve().parents[2]
FRAME = "source_robot_frame_unaligned_with_isaac"
SOURCE_FILES = ("response.json", "trajectory.npz", "metadata.json")
SIMULATOR_FILES = ("welding_prediction.py", "welding_scene_layout.py", "welding_workpiece.py",
                   "run_welding_sample.py", "run_welding_simulator.py", "welding_tool_geometry.py",
                   "rbpodo_description/robots/rb10_1300e_u.urdf", "ATU01035_welding_tool.usd")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


class SimulatorPredictionPackage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    schema_version: Literal["simulator-prediction-package-v1"] = "simulator-prediction-package-v1"
    package_id: UUID
    artifact_id: UUID
    attempt_id: UUID
    sample_id: str
    coordinate_frame: Literal["source_robot_frame_unaligned_with_isaac"] = FRAME
    point_count: int = Field(default=9, ge=2, le=4096)
    prediction_source: Literal['guided_vla','vlm_final_gpt','vlm_final_gpt2'] = 'guided_vla'
    simulation_only: Literal[True] = True
    physical_robot_executable: Literal[False] = False
    is_robot_executable: Literal[False] = False
    orientation_policy: Literal["fixed_initial_fixture_pose"] = "fixed_initial_fixture_pose"
    orientation_source: Literal["simulator_fixture_tool_policy; not VLA"] = "simulator_fixture_tool_policy; not VLA"
    ade_mm: float | None = Field(default=None,ge=0)
    fde_mm: float | None = Field(default=None,ge=0)
    directory: Path
    prediction_root: Path
    h5: Path
    obj: Path
    provenance: dict
    preflight: dict

    @model_validator(mode='after')
    def source_count(self):
        if (self.prediction_source=='guided_vla' and self.point_count!=9 or
                self.prediction_source=='vlm_final_gpt' and self.point_count!=33):
            raise ValueError('Existing prediction source count differs')
        if self.prediction_source!='vlm_final_gpt2' and (self.ade_mm is None or self.fde_mm is None):
            raise ValueError('Existing predictors require metrics')
        return self

    def summary(self):
        # Browser sees no filesystem paths, point arrays or native reasoning.
        return dict(package_id=str(self.package_id), artifact_id=str(self.artifact_id),
                    sample_id=self.sample_id, coordinate_frame=self.coordinate_frame,
                    point_count=self.point_count, prediction_source=self.prediction_source,
                    simulation_only=True, physical_robot_executable=False, is_robot_executable=False,
                    orientation_policy=self.orientation_policy, orientation_source=self.orientation_source,
                    ade_mm=self.ade_mm, fde_mm=self.fde_mm, preflight=self.preflight)


class FixtureInspector(Protocol):
    def inspect(self, root: Path, h5: Path, obj: Path, sample_id: str) -> dict: ...


class OfflineFixtureInspector:
    def __init__(self, python=NATIVE_PYTHON):
        # Existing audited native environment has numpy/scipy/h5py. This is not Isaac Python.
        self.python = Path(python)

    def inspect(self, root, h5, obj, sample_id):
        # Fixed audited native Python + fixed helper, never the Isaac launcher. No browser args.
        env = os.environ.copy()
        for name in list(env):
            if any(word in name.upper() for word in ("TOKEN", "API_KEY", "SECRET")):
                env.pop(name)
        env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        process = subprocess.run(
            [str(self.python), "-B", "-X", "utf8", str(PROJECT / "backend/simulator_fixture_probe.py")],
            input=json.dumps(dict(root=str(root), h5=str(h5), obj=str(obj), sample_id=sample_id)),
            cwd=PROJECT, env=env, shell=False, capture_output=True, text=True, encoding="utf-8",
            timeout=30, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if process.returncode:
            raise ValueError("Offline fixture probe failed; no Isaac process was launched")
        return json.loads(process.stdout)


@dataclass(frozen=True)
class PackageSettings:
    attempts: Path
    dataset_root: Path
    simulator_root: Path
    outputs: Path
    inputs: Path | None = None
    project: Path = PROJECT

    @classmethod
    def from_env(cls):
        # Reuse the existing backend-owned dataset binding, without constructing a VLA client.
        values = backend_env_values(PROJECT / '.env')
        inputs = Path(os.getenv("WELD_GUIDED_VLA_INPUTS") or values.get("WELD_GUIDED_VLA_INPUTS")
                      or PROJECT / ".cache/native-models/guided-vla-inputs.json").resolve()
        config = read(inputs)
        return cls(PROJECT / ".cache/native-models/guided-vla", Path(config["dataset_root"]).resolve(),
                   Path(os.getenv("WELD_SIM_ROOT") or values.get("WELD_SIM_ROOT") or PROJECT.parent / "simulator").resolve(),
                   PROJECT / ".cache/simulator/prediction-packages", inputs)


def query_assets(dataset_root, sample):
    return exact_assets(dataset_root, sample)


class SimulatorPredictionAdapter:
    def __init__(self, settings: PackageSettings, *, fixtures: FixtureInspector | None = None):
        self.settings = settings
        self.fixtures = fixtures or OfflineFixtureInspector()

    def _owned(self, path, parent):
        path = Path(path).resolve()
        if not path.is_relative_to(Path(parent).resolve()):
            raise ValueError("Artifact path is outside the backend-owned directory")
        return path

    def _attempt(self, artifact_id: UUID):
        matches = []
        for entry in self.settings.attempts.iterdir():
            if not entry.is_dir() or not re.fullmatch(r"[0-9a-f-]{36}", entry.name):
                continue
            try:
                metadata = read(self._owned(entry / "metadata.json", self.settings.attempts))
            except (OSError, ValueError):
                continue
            if metadata.get("artifact_id") == str(artifact_id):
                matches.append(self._owned(entry, self.settings.attempts))
        if len(matches) != 1:
            raise ValueError("Expected one completed Guided VLA artifact for this UUID")
        return matches[0]

    def _source(self, artifact_id):
        attempt = self._attempt(artifact_id)
        completion = read(attempt / "completion.json")
        if (completion.get("response_validated") is not True or completion.get("attempt_id") != attempt.name
                or set(completion["files"]) != set(SOURCE_FILES)):
            raise ValueError("VLA completion is invalid")
        hashes = {}
        for name in SOURCE_FILES:
            hashes[name] = sha(self._owned(attempt / name, attempt))
            if hashes[name] != completion["files"][name]:
                raise ValueError("Completed VLA artifact changed")
        response = read(attempt / "response.json")
        if response.get("artifact_id") != str(artifact_id):
            raise ValueError("Response artifact identity is missing or inconsistent")
        if response.get('source')=='vlm_final_gpt':
            # New explicit native-33 branch. Guided VLA's float32/n9 contract below stays exact.
            from backend.services.final_prediction_arrays import verify_gpt_arrays
            from backend.services.final_prediction_proof import verify_completed_gpt
            manifest=read(attempt/'request_manifest.json')
            if not manifest.get('workflow_job_id'):raise ValueError('GPT requires Workflow binding')
            if not hasattr(self,'storage'):raise ValueError('GPT requires current Workflow adapter')
            job=self.storage.get_job(self.job_id).model_dump(mode='json')
            verify_completed_gpt(attempt,manifest,job)
            trajectory=verify_gpt_arrays(attempt,response,manifest)
            return attempt,trajectory,manifest,hashes,(attempt/'trajectory.npz').read_bytes()
        trajectory = VLAPredictedTrajectory.model_validate(response)
        metadata, manifest = read(attempt / "metadata.json"), read(attempt / "request_manifest.json")
        expected = metadata_for(trajectory.sample_id)
        if trajectory.coordinate_frame != FRAME:
            raise ValueError("COORDINATE_FRAME_CONTRACT_MISMATCH")
        if (any(metadata.get(k) != v for k, v in expected.items()) or
                metadata.get("artifact_id") != str(artifact_id) or metadata.get("attempt_id") != attempt.name or
                metadata.get("artifact_type") != "VLAPredictedTrajectory" or metadata.get("is_robot_executable") is not False or
                metadata.get("split") != trajectory.split or manifest.get("sample_id") != trajectory.sample_id or
                manifest.get("split") != trajectory.split or manifest.get("attempt_id") != attempt.name or
                manifest.get("reference_in_request") is not False or not manifest.get("approved_at")):
            raise ValueError("Query/episode/approval identity differs")
        for name, digest in manifest["files"].items():
            if sha(self._owned(attempt / name, attempt)) != digest:
                raise ValueError("VLA input snapshot changed")
        for path_key, hash_key in (("source_job", "source_job_sha256"), ("source_mask", "source_mask_sha256")):
            if sha(self._owned(manifest[path_key], self.settings.project)) != manifest[hash_key]:
                raise ValueError("Current source job/mask differs from approved VLA input")
        if self.settings.inputs and sha(self.settings.inputs) != manifest["inputs_sha256"]:
            raise ValueError("Backend dataset binding changed")
        data = (attempt / "trajectory.npz").read_bytes()
        with np.load(io.BytesIO(data), allow_pickle=False) as arrays:
            if set(arrays.files) != {"predicted_path_m", "ground_truth_path_m"}:
                raise ValueError("Unexpected Guided VLA NPZ schema")
            for key, points in (("predicted_path_m", trajectory.predicted_path_xyz_mm),
                                ("ground_truth_path_m", trajectory.ground_truth_path_xyz_mm)):
                actual = arrays[key]
                expected_points = np.asarray(points, dtype=np.float32) * np.float32(.001)
                if (actual.shape != (9, 3) or actual.dtype != np.float32 or not np.isfinite(actual).all()
                        or not np.array_equal(actual, expected_points)):
                    raise ValueError("NPZ differs from validated response/units/shape")
        return attempt, trajectory, manifest, hashes, data

    def prepare(self, artifact_id: UUID) -> SimulatorPredictionPackage:
        try:
            artifact_id = UUID(str(artifact_id))
            attempt, trajectory, manifest, hashes, data = self._source(artifact_id)
            if getattr(trajectory,'source',None)=='vlm_final_gpt':raise ValueError('GPT requires dataset_v2/dataset_stp preview')
            h5, obj = query_assets(self.settings.dataset_root, trajectory.sample_id)
            if not h5.is_file() or not obj.is_file():
                raise ValueError("Matching query H5/OBJ asset is missing")
            h5 = self._owned(h5, self.settings.dataset_root)
            obj = self._owned(obj, self.settings.dataset_root)
            if h5.stem != trajectory.sample_id or obj.stem != trajectory.sample_id:
                raise ValueError("H5/fixture identity differs")
            sim_hashes = {name: sha(self.settings.simulator_root / name) for name in SIMULATOR_FILES}
            # Verify the meshes named by the actual robot URDF without importing Isaac.
            urdf = ET.parse(self.settings.simulator_root / "rbpodo_description/robots/rb10_1300e_u.urdf")
            for mesh in urdf.findall(".//mesh"):
                filename = mesh.attrib["filename"]
                if not filename.startswith("package://rbpodo_description/"):
                    raise ValueError("Unknown robot mesh mapping")
                name = filename.removeprefix("package://")
                sim_hashes[name] = sha(self._owned(self.settings.simulator_root / name, self.settings.simulator_root))
            fixture = self.fixtures.inspect(self.settings.simulator_root, h5, obj, trajectory.sample_id)
            if fixture.get("sample_id") != trajectory.sample_id:
                raise ValueError("Fixture probe identity differs")
            outputs = self._owned(self.settings.outputs, self.settings.project / ".cache")
            if outputs.is_relative_to(attempt) or outputs.is_relative_to(self.settings.simulator_root.resolve()):
                raise ValueError("Package outputs must be separate owned cache files")
            package_id = uuid4()
            directory = outputs / str(package_id)
            episode = directory / "predictions" / trajectory.sample_id
            episode.mkdir(parents=True, exist_ok=False)
            with (episode / "trajectory.npz").open("xb") as stream:
                stream.write(data)  # Exact byte copy; never interpolate or replace predictions.
            write(episode / "metadata.json", metadata_for(trajectory.sample_id))
            check = inspect_legacy_prediction(episode / "trajectory.npz", h5, trajectory.sample_id)
            if check["prediction_sha256"] != hashes["trajectory.npz"]:
                raise ValueError("Prediction copy differs")
            ready = fixture.get("ready") is True
            verdict = ("GUIDED_VLA_SIMULATOR_OFFLINE_READY" if ready else
                       "B_PR_FIXTURE_SUPPORT_REQUIRED" if trajectory.sample_id.startswith("B_PR_") else
                       "SIMULATOR_INPUT_CONTRACT_BLOCKED")
            preflight = dict(verdict=verdict, package_contract="PASS", fixture_ready=ready,
                             gt_h5_frame_error_mm_max=check["gt_h5_frame_error_mm_max"],
                             n9_supported=True, fixture=fixture, live_called=False)
            provenance = dict(source_attempt=str(attempt), source_files=hashes,
                              request_manifest_sha256=sha(attempt / "request_manifest.json"),
                              completion_sha256=sha(attempt / "completion.json"),
                              source_mask_id=manifest["source_mask_id"], approved_at=manifest["approved_at"],
                              source_mask=manifest["source_mask"],
                              source_mask_sha256=manifest["source_mask_sha256"],
                              source_job=manifest["source_job"], source_job_sha256=manifest["source_job_sha256"],
                              h5_sha256=check["h5_sha256"], obj_sha256=sha(obj), simulator_files=sim_hashes,
                              metadata_sha256=sha(episode / "metadata.json"),
                              start_xyz_source=(trajectory.input_sources or {}).get("start_xyz")
                              if isinstance(trajectory.input_sources, dict) else None,
                              frame_evidence="GT matches query H5 XYZ directly after mm->m/index resampling; "
                              "no axis permutation, sign flip, centering, start subtraction or fitted alignment. "
                              "Prediction shares declared/export convention; accuracy and world calibration are not proven.")
            package = SimulatorPredictionPackage(package_id=package_id, artifact_id=artifact_id,
                       attempt_id=UUID(attempt.name), sample_id=trajectory.sample_id,
                       ade_mm=trajectory.ade_mm, fde_mm=trajectory.fde_mm, directory=directory,
                       prediction_root=episode.parent, h5=h5, obj=obj, provenance=provenance, preflight=preflight)
            write(directory / "package.json", package.model_dump(mode="json"))
            return package
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, ET.ParseError):
            raise WorkflowError("Simulator input contract blocked: completed artifact, query assets, frame or approval verification failed.", 409) from None

    def verify(self, package: SimulatorPredictionPackage):
        """Repeat source/asset/geometry checks at admission; never trust a browser package."""
        attempt, trajectory, manifest, hashes, _ = self._source(package.artifact_id)
        if (package.attempt_id != UUID(attempt.name) or package.sample_id != trajectory.sample_id or
                sha(attempt / "request_manifest.json") != package.provenance["request_manifest_sha256"] or
                sha(attempt / "completion.json") != package.provenance["completion_sha256"] or
                hashes != package.provenance["source_files"] or sha(package.h5) != package.provenance["h5_sha256"] or
                sha(package.obj) != package.provenance["obj_sha256"] or
                sha(package.prediction_root / package.sample_id / "trajectory.npz") != hashes["trajectory.npz"] or
                sha(package.prediction_root / package.sample_id / "metadata.json") != package.provenance["metadata_sha256"]):
            raise ValueError("Simulator package/source changed")
        if any(sha(self.settings.simulator_root / name) != digest
               for name, digest in package.provenance["simulator_files"].items()):
            raise ValueError("Audited simulator source/assets changed")
        if self.fixtures.inspect(self.settings.simulator_root, package.h5, package.obj, package.sample_id) != package.preflight["fixture"]:
            raise ValueError("Fixture contract changed")


class CurrentVLASimulatorService:
    """Separate explicit human action; absent from Agent tools and Workflow.plan."""
    def __init__(self, simulator, *, adapter=None):
        self.simulator, self.adapter = simulator, adapter

    def prepare(self, artifact_id: UUID):
        try:
            adapter = self.adapter or SimulatorPredictionAdapter(PackageSettings.from_env())
            config = getattr(self.simulator, "config", None)
            if config and config.root.resolve() != adapter.settings.simulator_root.resolve():
                raise ValueError("Runtime simulator root differs from audited source")
            return adapter, adapter.prepare(artifact_id)
        except (OSError, ValueError, KeyError, TypeError):
            raise WorkflowError("Current VLA simulator package is not configured or invalid.", 409) from None

    def preflight(self, artifact_id: UUID):
        _, package = self.prepare(artifact_id)
        return package.summary()

    def run_current_vla_prediction(self, artifact_id: UUID):
        adapter, package = self.prepare(artifact_id)
        if package.preflight["fixture_ready"] is not True:
            raise WorkflowError(package.preflight["verdict"] + ": current prediction was not queued.", 409)
        try:
            adapter.verify(package)
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            raise WorkflowError("Simulator package changed; current prediction was not queued.", 409) from None
        method = getattr(self.simulator, "run_current_vla_prediction", None)
        if method is None:
            raise WorkflowError("Current VLA playback is unavailable in this SimulatorClient.", 409)
        return method(package)
