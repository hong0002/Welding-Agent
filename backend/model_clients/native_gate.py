"""Stdlib launch gate: parent assigns process ownership BEFORE releasing native CLI."""
import json
import subprocess
import sys


if __name__ == "__main__":
    command = json.loads(sys.stdin.readline())
    # Only backend-generated argv arrives here; no shell or source imports.
    result = subprocess.run(command, shell=False, stdin=subprocess.DEVNULL)
    raise SystemExit(result.returncode)
