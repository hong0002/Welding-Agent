"""Explicit, bounded import-only check. No SimulationApp instance or simulator script."""
import argparse
from collections import deque
import json
import threading
import time

from dotenv import load_dotenv

from backend.services.simulator_client import SimulatorConfig, timestamp
from backend.services.simulator_diagnostics import write_import_check
from backend.services.simulator_process import ProcessLauncher


def check_environment(config, timeout=45, launcher=None):
    result = dict(status="failed", checked_at=timestamp(), message="Import check did not complete")
    lines = deque(maxlen=80)
    process = None
    reader = None
    try:
        if errors := config.start_errors():
            raise ValueError(" ".join(errors))
        process = (launcher or ProcessLauncher()).probe(config.executable, config.root)
        def read():
            while line := process.stdout.readline(4096):
                lines.append(line.rstrip())
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        deadline = time.monotonic() + timeout
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(.05)
        if process.poll() is None:
            raise TimeoutError("Isaac import check timed out")
        reader.join(timeout=2)
        if process.poll() != 0:
            raise RuntimeError(f"Isaac import check exited with code {process.poll()}")
        marker = next((line for line in lines if line.startswith("[ISAAC_IMPORT_CHECK] ")), None)
        if marker is None:
            raise RuntimeError("Missing explicit Isaac import success signal")
        result.update(json.loads(marker.removeprefix("[ISAAC_IMPORT_CHECK] ")),
                      message="Imports passed; no SimulationApp instance was created. GUI compatibility is not checked.")
    except Exception as exc:
        result["message"] = str(exc)
    finally:
        if process:
            process.stop()
        if reader:
            reader.join(timeout=2)
        if process:
            process.stdout.close()
    result["output"] = list(lines)
    write_import_check(config, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args()
    load_dotenv(args.env_file, override=True)
    result = check_environment(SimulatorConfig.from_env())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 1)
