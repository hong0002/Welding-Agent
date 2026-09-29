import hashlib
import json
from pathlib import Path
from uuid import uuid4

import h5py
import numpy as np
import pytest

from backend.services.legacy_prediction_adapter import (
    find_h5, find_legacy_prediction, import_legacy_prediction, inspect_legacy_prediction, metadata_for,
)


@pytest.fixture
def legacy(tmp_path):
    sample = "L_PR_03_0001"
    episode = tmp_path / "predictions" / ("0000_" + sample)
    episode.mkdir(parents=True)
    teaching = tmp_path / "Other" / "Other" / "로봇티칭데이터" / "03(3mm)" / sample
    teaching.mkdir(parents=True)
    h5 = teaching / (sample + ".h5")
    source = np.column_stack([np.linspace(710, 750, 150), np.linspace(20, -30, 150), np.linspace(320, 280, 150)])
    with h5py.File(h5, "w") as handle:
        handle["trajectory"] = np.column_stack([source, np.zeros_like(source)])
    gt = np.column_stack([np.interp(np.linspace(0,149,33),np.arange(150),source[:,j]) * .001 for j in range(3)])
    np.savez(episode / "trajectory.npz", predicted_path_m=gt+.003, ground_truth_path_m=gt)
    return sample, episode, h5, gt


def test_missing_metadata_import_uses_exact_contract_and_does_not_mutate_sources(legacy):
    sample, episode, h5, gt = legacy
    output = Path(__file__).resolve().parents[1] / ".cache" / "legacy-tests" / uuid4().hex
    original = (episode / "trajectory.npz").read_bytes()
    original_h5 = h5.read_bytes()
    report = import_legacy_prediction(episode.parent, h5.parents[3], sample, output)
    assert report["point_count"] == 33 and report["gt_h5_frame_error_mm_max"] < .05
    assert (output / sample / "trajectory.npz").read_bytes() == original
    assert json.loads((output / sample / "metadata.json").read_text()) == {
        "episode_id": sample, "coordinate_frame": "source_robot_frame_unaligned_with_isaac",
        "source_units": "mm", "scale_to_meters": .001,
    }
    assert not (episode / "metadata.json").exists()
    assert (episode / "trajectory.npz").read_bytes() == original and h5.read_bytes() == original_h5
    assert report["prediction_sha256"] == hashlib.sha256(original).hexdigest()
    with pytest.raises(ValueError, match="already exists"):
        import_legacy_prediction(episode.parent, h5.parents[3], sample, output)


def test_directory_and_h5_episode_mapping(legacy):
    sample, episode, h5, _ = legacy
    assert find_legacy_prediction(episode.parent, sample) == episode / "trajectory.npz"
    assert find_h5(h5.parents[3], sample) == h5
    with pytest.raises(ValueError, match="found 0"):
        find_legacy_prediction(episode.parent, "L_PR_03_0002")
    with pytest.raises(ValueError, match="does not match"):
        inspect_legacy_prediction(episode / "trajectory.npz", h5, "L_PR_03_0002")


@pytest.mark.parametrize("change", ["different_sample", "units", "nan", "shape", "length", "source_units"])
def test_invalid_prediction_or_wrong_geometric_mapping(legacy, change):
    sample, episode, h5, gt = legacy
    predicted = gt.copy()
    extra = {}
    if change == "different_sample": gt = gt + .002
    if change == "units": gt = gt * 1000
    if change == "nan": predicted[2,0] = np.nan
    if change == "shape": predicted = np.zeros((33,6))
    if change == "length": predicted = predicted[:-1]
    if change == "source_units": extra["predicted_path_xyz"] = predicted * 2
    np.savez(episode / "trajectory.npz", predicted_path_m=predicted, ground_truth_path_m=gt, **extra)
    with pytest.raises(ValueError):
        inspect_legacy_prediction(episode / "trajectory.npz", h5, sample)


def test_existing_conflicting_metadata_is_not_overwritten(legacy):
    sample, episode, h5, _ = legacy
    metadata = metadata_for(sample); metadata["source_units"] = "m"
    path = episode / "metadata.json"; path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="conflicts"):
        inspect_legacy_prediction(episode / "trajectory.npz", h5, sample)
    assert json.loads(path.read_text())["source_units"] == "m"


def test_ambiguous_mapping_rejected(legacy):
    sample, episode, h5, _ = legacy
    duplicate = episode.parent / sample; duplicate.mkdir()
    (duplicate / "trajectory.npz").write_bytes((episode / "trajectory.npz").read_bytes())
    with pytest.raises(ValueError, match="found 2"):
        find_legacy_prediction(episode.parent, sample)
    (h5.parent.parent / h5.name).write_bytes(h5.read_bytes())
    with pytest.raises(ValueError, match="found 2"):
        find_h5(h5.parents[3], sample)


def test_output_cannot_escape_project_cache(legacy, tmp_path):
    sample, episode, h5, _ = legacy
    with pytest.raises(ValueError, match="inside Welding-Agent/.cache"):
        import_legacy_prediction(episode.parent, h5.parent, sample, Path(__file__).parent / "forbidden-output")


def test_wrong_directory_prefix_not_accepted(legacy):
    sample, episode, h5, _ = legacy
    other = episode.with_name("0000_L_PR_03_0002"); episode.rename(other)
    with pytest.raises(ValueError, match="mapping"):
        inspect_legacy_prediction(other / "trajectory.npz", h5, sample)
