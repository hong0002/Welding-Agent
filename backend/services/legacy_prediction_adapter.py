"""Validate missing-metadata exports against H5, then stage an unchanged NPZ locally.

Contract source: external welding_prediction.prediction_index/prediction_targets.
No fitting/alignment, GT substitution, prediction edits or source writes are allowed.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import re
import shutil
from uuid import uuid4

MAX_FRAME_ERROR_MM = 0.05


def metadata_for(sample_id: str):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", sample_id):
        raise ValueError("Invalid sample ID")
    # Exactly the four fields required by the inspected noninteractive pipeline.
    return dict(episode_id=sample_id, coordinate_frame="source_robot_frame_unaligned_with_isaac",
                source_units="mm", scale_to_meters=0.001)


def find_legacy_prediction(prediction_root: Path | str, sample_id: str) -> Path:
    metadata_for(sample_id)
    root = Path(prediction_root)
    matches = sorted(p / "trajectory.npz" for p in root.iterdir()
                     if p.is_dir() and re.fullmatch(rf"(?:\d+_)?{re.escape(sample_id)}", p.name)
                     and (p / "trajectory.npz").is_file())
    if len(matches) != 1:
        raise ValueError(f"Expected one legacy episode directory for {sample_id}; found {len(matches)} under {root}")
    return matches[0].resolve()


def find_h5(samples_dir: Path | str, sample_id: str) -> Path:
    metadata_for(sample_id)
    matches = sorted(p for p in Path(samples_dir).rglob("*")
                     if p.is_file() and p.suffix.lower() == ".h5" and p.stem == sample_id)
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one H5 with stem {sample_id}; found {len(matches)}")
    return matches[0].resolve()


def inspect_legacy_prediction(prediction_file: Path | str, h5_file: Path | str, sample_id: str) -> dict:
    import h5py
    import numpy as np

    expected_metadata = metadata_for(sample_id)
    source, h5_path = Path(prediction_file).resolve(), Path(h5_file).resolve()
    if h5_path.stem != sample_id:
        raise ValueError("H5 sample ID does not match the selected episode")
    if not re.fullmatch(rf"(?:\d+_)?{re.escape(sample_id)}", source.parent.name):
        raise ValueError("Legacy directory/sample ID mapping does not match")
    metadata_path = source.with_name("metadata.json")
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if any(metadata.get(key) != value for key, value in expected_metadata.items()):
            raise ValueError("Existing metadata conflicts with the verified legacy contract")
    prediction_bytes, h5_bytes = source.read_bytes(), h5_path.read_bytes()
    with h5py.File(io.BytesIO(h5_bytes), "r") as handle:
        trajectory = np.asarray(handle["trajectory"], dtype=float)
    if (trajectory.ndim != 2 or trajectory.shape[1] not in (3, 6) or len(trajectory) < 2
            or not np.isfinite(trajectory).all()):
        raise ValueError("H5 trajectory must contain finite N>=2 rows of XYZ or XYZ/RPY")
    with np.load(io.BytesIO(prediction_bytes), allow_pickle=False) as arrays:
        predicted = np.asarray(arrays["predicted_path_m"], dtype=float)
        gt = np.asarray(arrays["ground_truth_path_m"], dtype=float)
        for name, points in (("predicted", predicted), ("ground_truth", gt)):
            if points.ndim != 2 or points.shape[1] != 3 or len(points) < 2 or not np.isfinite(points).all():
                raise ValueError(f"{name}: expected finite (N>=2,3) XYZ in meters")
            original_key = name + "_path_xyz"
            if original_key in arrays and not np.allclose(points, arrays[original_key] * .001, atol=1e-7, rtol=0):
                raise ValueError(f"{name}: inconsistent source-unit/meter arrays")
        if predicted.shape != gt.shape:
            raise ValueError("Prediction and ground truth lengths differ")
    expected = np.column_stack([
        np.interp(np.linspace(0, len(trajectory) - 1, len(gt)), np.arange(len(trajectory)), trajectory[:, axis]) * .001
        for axis in range(3)])
    error_mm = float(np.linalg.norm(gt - expected, axis=1).max() * 1000)
    if error_mm > MAX_FRAME_ERROR_MM:
        raise ValueError(f"Wrong sample/frame/units: GT vs H5 error {error_mm:.6f} mm exceeds {MAX_FRAME_ERROR_MM} mm")
    return dict(sample_id=sample_id, source_prediction=str(source), source_h5=str(h5_path),
                prediction_sha256=hashlib.sha256(prediction_bytes).hexdigest(),
                h5_sha256=hashlib.sha256(h5_bytes).hexdigest(),
                point_count=len(gt), gt_h5_frame_error_mm_max=error_mm, metadata=expected_metadata)


def import_legacy_prediction(prediction_root: Path | str, samples_dir: Path | str,
                             sample_id: str, output_root: Path | str) -> dict:
    source = find_legacy_prediction(prediction_root, sample_id)
    h5_path = find_h5(samples_dir, sample_id)
    report = inspect_legacy_prediction(source, h5_path, sample_id)
    output = Path(output_root).resolve()
    cache_root = (Path(__file__).resolve().parents[2] / ".cache").resolve()
    if not output.is_relative_to(cache_root):
        raise ValueError("Imported prediction output must stay inside Welding-Agent/.cache")
    for original in (Path(prediction_root).resolve(), Path(samples_dir).resolve()):
        if output.is_relative_to(original):
            raise ValueError("Imported output must not be inside an original input directory")
    output.mkdir(parents=True, exist_ok=True)
    destination = output / sample_id
    if destination.exists():
        raise ValueError("Imported episode already exists; use a fresh output directory")
    staging = output / (".import-" + uuid4().hex)
    staging.mkdir()
    try:
        shutil.copyfile(source, staging / "trajectory.npz")
        # Recheck the copy against the inspected source in case files changed during import.
        if hashlib.sha256((staging / "trajectory.npz").read_bytes()).hexdigest() != report["prediction_sha256"]:
            raise ValueError("Prediction changed while importing; retry with stable source files")
        (staging / "metadata.json").write_text(json.dumps(report["metadata"], indent=2), encoding="utf-8")
        (staging / "import_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        staging.rename(destination)
    except BaseException:
        # Only fixed files in this freshly created staging directory, no recursive deletion.
        for name in ("trajectory.npz", "metadata.json", "import_report.json"):
            (staging / name).unlink(missing_ok=True)
        staging.rmdir()
        raise
    return dict(report, imported_prediction_root=str(output))
