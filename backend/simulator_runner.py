"""Run an unchanged external script after the parent establishes process ownership."""
import runpy
import sys
import json
import os
from pathlib import Path


if __name__ == "__main__":
    manifest = json.loads(os.environ.pop("WELD_SIM_RUN_MANIFEST"))
    if manifest["mode"] == "probe":
        # Import only: never instantiate SimulationApp or create a GUI here.
        from isaacsim import SimulationApp
        import numpy, scipy, h5py
        print('[ISAAC_IMPORT_CHECK] ' + json.dumps(dict(status="passed", python=sys.executable,
              modules=["isaacsim.SimulationApp", "numpy", "scipy", "h5py"])), flush=True)
        raise SystemExit(0)
    if manifest["mode"] != "script":
        raise SystemExit("Unsupported runner mode")
    script = Path(manifest["script"]).resolve()
    if script.name not in {"run_welding_simulator.py", "run_welding_sample.py"}:
        raise SystemExit("Script is not allowlisted")
    if legacy := manifest.get("legacy_prediction"):
        if script.name != "run_welding_sample.py":
            raise SystemExit("Legacy import is only supported for the existing sample")
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from backend.services.legacy_prediction_adapter import import_legacy_prediction
        report = import_legacy_prediction(**legacy)
        print('[LEGACY_PREDICTION] ' + json.dumps(report, ensure_ascii=True), flush=True)
    sys.path.insert(0, str(script.parent))
    sys.argv = [str(script), *manifest["arguments"]]
    runpy.run_path(str(script), run_name="__main__")
