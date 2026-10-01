"""Stdlib-only admission recheck inside the owned simulator child before execution."""
import hashlib
import json
from pathlib import Path
from uuid import UUID


def verify_current_package(claim, simulator_root, arguments, *, project=None):
    project = (project or Path(__file__).resolve().parents[2]).resolve()
    path = Path(claim["package"]).resolve()
    outputs = project / ".cache/simulator/prediction-packages"
    if path.name != "package.json" or not path.is_relative_to(outputs) or str(UUID(path.parent.name)) != path.parent.name:
        raise ValueError("Current package must be backend-owned")
    def sha(file):
        return hashlib.sha256(Path(file).read_bytes()).hexdigest()
    if sha(path) != claim["sha256"]:
        raise ValueError("Admitted package changed")
    package = json.loads(path.read_text(encoding="utf-8"))
    sample, provenance = package["sample_id"], package["provenance"]
    if (package["schema_version"] != "simulator-prediction-package-v1" or package["point_count"] != 9 or
            package["simulation_only"] is not True or package["physical_robot_executable"] is not False or
            package["is_robot_executable"] is not False or
            package["coordinate_frame"] != "source_robot_frame_unaligned_with_isaac" or
            package["preflight"]["fixture_ready"] is not True or package["preflight"]["fixture"]["sample_id"] != sample):
        raise ValueError("Current artifact/fixture contract is invalid")
    prediction_root = Path(package["prediction_root"]).resolve()
    if prediction_root != path.parent / "predictions" or Path(package["directory"]).resolve() != path.parent:
        raise ValueError("Prediction root differs from owned package")
    h5, obj = Path(package["h5"]).resolve(), Path(package["obj"]).resolve()
    if h5.stem != sample or obj.stem != sample:
        raise ValueError("Query H5/fixture identity differs")
    def arg(name):
        return arguments[arguments.index(name) + 1]
    if ("--send" not in arguments or "--prediction" not in arguments or arg("--sample") != sample or
            Path(arg("--samples-dir")).resolve() != h5.parent or
            Path(arg("--prediction-root")).resolve() != prediction_root):
        raise ValueError("Current playback arguments differ from admitted artifact")
    source = Path(provenance["source_attempt"]).resolve()
    if not source.is_relative_to(project / ".cache/native-models/guided-vla"):
        raise ValueError("VLA source must be backend-owned")
    for name, digest in provenance["source_files"].items():
        if name not in {"response.json", "trajectory.npz", "metadata.json"} or sha(source / name) != digest:
            raise ValueError("Completed VLA source changed")
    checks = [(h5, provenance["h5_sha256"]), (obj, provenance["obj_sha256"]),
              (source / "request_manifest.json", provenance["request_manifest_sha256"]),
              (source / "completion.json", provenance["completion_sha256"]),
              (provenance["source_job"], provenance["source_job_sha256"]),
              (provenance["source_mask"], provenance["source_mask_sha256"]),
              (prediction_root / sample / "trajectory.npz", provenance["source_files"]["trajectory.npz"]),
              (prediction_root / sample / "metadata.json", provenance["metadata_sha256"])]
    for name, digest in provenance["simulator_files"].items():
        asset = (Path(simulator_root) / name).resolve()
        if not asset.is_relative_to(Path(simulator_root).resolve()):
            raise ValueError("Unexpected simulator asset path")
        checks.append((asset, digest))
    if any(sha(file) != digest for file, digest in checks):
        raise ValueError("Current prediction/asset/provenance changed before execution")
