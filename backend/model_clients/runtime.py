import json
import os
import subprocess
import sys
import time
from pathlib import Path
from threading import Lock
from uuid import uuid4

from PIL import Image

from backend.model_clients.config import ROOT, ModelSettings
from backend.model_clients.contracts import ModelFault


class ModelRuntime:
    """One bounded Python worker, no shell, no heavy startup or inferred Python environment."""
    def __init__(self, settings: ModelSettings, *, cache: Path | None = None, run=subprocess.run):
        self.settings = settings
        self.cache = cache or ROOT / ".cache/models"
        self.run = run
        self.lock = Lock()
        self.last_error = None
        self.verified = False
        self.running = False

    def status(self):
        configured = self.settings.configured()
        return {"backend": self.settings.backend, "configured": configured,
                "ready": configured and self.verified and self.last_error is None and not self.running,
                "state": "NOT_CONFIGURED" if not configured else "RUNNING" if self.running else "FAILED" if self.last_error else "READY" if self.verified else "UNVERIFIED",
                "code": self.last_error, "reference_mode": self.settings.reference_mode or None}

    def infer(self, image: Image.Image, payload: dict):
        if self.settings.backend != "experimental" or not self.settings.configured():
            raise ModelFault("MODEL_NOT_CONFIGURED")
        with self.lock:
            started = time.monotonic()
            directory = self.cache / str(uuid4())
            directory.mkdir(parents=True)
            image.save(directory / "image.png")
            request = {**payload, "stage": self.settings.stage, "repository": str(self.settings.repository),
                       "camera": self.settings.camera, "timeout": self.settings.timeout,
                       "reference_mode": self.settings.reference_mode,
                       "references": str(self.settings.references) if self.settings.references else None}
            (directory / "input.json").write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
            env = {key: value for key, value in os.environ.items()
                   if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "SSL_CERT_FILE", "SSL_CERT_DIR"}}
            env.update(OPENAI_API_KEY=self.settings.api_key, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
            try:
                self.running = True
                result = self.run([str(self.settings.python), "-B", str(Path(__file__).with_name("worker.py")),
                                   str(directory / "input.json")], cwd=directory, env=env, shell=False,
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  timeout=self.settings.timeout, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
                output_path = directory / "output.json"
                if not output_path.is_file() or output_path.stat().st_size > 8_000_000:
                    raise ModelFault("MODEL_PROCESS_FAILED")
                output = json.loads(output_path.read_text(encoding="utf-8"))
                if result.returncode or "error" in output:
                    raise ModelFault(output.get("error", "MODEL_PROCESS_FAILED"))
                output["latency_ms"] = (time.monotonic() - started) * 1000
                output["artifact_directory"] = directory
                output["artifact_id"] = directory.name
                self.last_error = None
                self.verified = True
                return output
            except subprocess.TimeoutExpired:
                self.last_error = "MODEL_TIMEOUT"
                raise ModelFault(self.last_error) from None
            except ModelFault as exc:
                self.last_error = exc.code
                raise
            except Exception:
                self.last_error = "MODEL_PROCESS_FAILED"
                raise ModelFault(self.last_error) from None
            finally:
                self.running = False
