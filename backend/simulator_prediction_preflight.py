"""Offline one-artifact audit CLI. Never starts inference, simulation, IK or a GUI."""
import argparse
import contextlib
import importlib.util
import io
import json
import sys
from uuid import UUID

import h5py
import numpy as np

from backend.services.simulator_prediction_package import PackageSettings, SimulatorPredictionAdapter, sha, write


def audit(artifact_id):
    settings = PackageSettings.from_env()
    adapter = SimulatorPredictionAdapter(settings)
    package = adapter.prepare(artifact_id)
    adapter.verify(package)
    before = dict(package.provenance["source_files"])
    with h5py.File(package.h5, "r") as handle:
        source = np.asarray(handle["trajectory"], dtype=float)
        source_attrs = bool(handle.attrs)
    if source.shape[1] == 3:
        source = np.column_stack((source, np.zeros_like(source)))
    # Only the inspected pure numpy/json loader. This is a schema/frame probe,
    # using identity transform explicitly; it is NOT a B_PR fixture placement.
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("offline_prediction_contract", settings.simulator_root / "welding_prediction.py")
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    with contextlib.redirect_stdout(io.StringIO()):
        index = loader.prediction_index(package.prediction_root)
        _, arrays, loader_report = loader.prediction_targets(index[package.sample_id], package.sample_id,
                                                             source, source, np.eye(4))
    report = dict(verdict=package.preflight["verdict"], package=package.model_dump(mode="json"),
                  external_loader=dict(status="PASS", point_count=len(arrays["predicted_source_xyz_m"]),
                      transform="identity solely for offline loader contract probe; not fixture placement",
                      gt_h5_frame_error_mm_max=loader_report["gt_h5_frame_error_mm_max"],
                      simulator_ade_excluding_start_mm=loader_report["ade_mm"],
                      simulator_fde_mm=loader_report["fde_mm"],
                      server_ade_mm_preserved=package.ade_mm, server_fde_mm_preserved=package.fde_mm),
                  frame_semantics=dict(source_start_norm_mm=float(np.linalg.norm(source[0,:3])),
                      absolute_vs_relative="Absolute query H5 source XYZ; no start subtraction or centering",
                      axis_units_origin="Direct XYZ index order, mm->m only; no sign flip or origin correction required for GT agreement",
                      h5_has_frame_attributes=source_attrs,
                      prediction="Same declared/export convention as response GT; numerical accuracy and real-world registration are separate",
                      source_to_scene="Not available for B_PR until a verified contact seam and fixture approach policy exists",
                      calibrated_robot_world=False),
                  original_artifact_unchanged=all(sha(settings.attempts/str(package.attempt_id)/name)==digest
                                                 for name,digest in before.items()),
                  execution_counts={name:0 for name in ("Segment","Rough","trajectory2","Guided VLA","OpenAI","SSH retrieval","Isaac")})
    write(package.directory / "offline_audit.json", report)
    print(json.dumps(dict(verdict=report["verdict"], package=str(package.directory / "package.json"),
                         report=str(package.directory / "offline_audit.json"), artifact_id=str(package.artifact_id),
                         point_count=9, gt_h5_frame_error_mm_max=loader_report["gt_h5_frame_error_mm_max"],
                         original_artifact_unchanged=report["original_artifact_unchanged"],
                         ade_mm=package.ade_mm, fde_mm=package.fde_mm, execution_counts=report["execution_counts"]),
                     ensure_ascii=False, indent=2))
    return package


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-id", type=UUID, required=True)
    audit(parser.parse_args().artifact_id)
