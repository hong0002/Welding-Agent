"""Cached diagnostics; status reads never start an external interpreter."""
import json
import os


def launcher_identity(config):
    launcher = config.executable
    return {"launcher": str(launcher) if launcher else None,
            "mtime_ns": launcher.stat().st_mtime_ns if launcher and launcher.is_file() else None}


def read_import_check(config):
    path = config.runtime_dir / "import-check.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["identity"] == launcher_identity(config):
            return record["result"]
    except (OSError, ValueError, KeyError):
        pass
    return {"status": "not_run", "message": "Run python -m backend.simulator_smoke --env-file .env explicitly; status never starts Isaac."}


def write_import_check(config, result):
    path = config.runtime_dir / "import-check.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(dict(identity=launcher_identity(config), result=result), indent=2), encoding="utf-8")
    temporary.replace(path)
