"""Release a fixed launcher only after parent Job Object/process-group ownership."""
import json
import os
import subprocess
import sys


if __name__ == "__main__":
    if sys.stdin.readline().strip() != "START":
        raise SystemExit("Missing launcher ownership gate")
    command = json.loads(os.environ.pop("WELD_SIM_LAUNCH_COMMAND"))
    process = subprocess.run(command, shell=False, stdin=subprocess.DEVNULL)
    raise SystemExit(process.returncode)
