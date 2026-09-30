import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ModelSettings:
    stage: str
    backend: str = "dummy"
    repository: Path | None = None
    python: Path | None = None
    api_key: str = field(default="", repr=False)
    timeout: float = 120
    reference_mode: str = ""
    references: Path | None = None
    camera: str = "web"
    native_config: Path | None = None
    native_binding: Path | None = None

    @classmethod
    def from_env(cls, stage: str):
        values = dotenv_values(ROOT / ".env", interpolate=False)
        prefix = f"WELD_{stage.upper()}_"
        def get(name, default=""):
            return (os.environ.get(prefix + name, values.get(prefix + name) or default)).strip()
        def path(name, default=""):
            value = get(name, default)
            return Path(value).expanduser().resolve() if value else None
        native = get("BACKEND", "dummy") in ("native", "real")
        default_timeout = 900 if native else 120 if stage == "segment" else 180
        try:
            timeout = float(get("TIMEOUT", str(default_timeout)))
            if not 1 <= timeout <= (900 if native else 300):
                timeout = default_timeout
        except ValueError:
            timeout = default_timeout
        sibling = {"segment": "vlm_segment", "rough3d": "vlm_trajectory2"}.get(stage, "vlm_trajectory")
        return cls(stage=stage, backend=get("BACKEND", "dummy"), repository=path("REPO", str(ROOT.parent / sibling)),
                   python=path("PYTHON"), api_key=(values.get("OPENAI_API_KEY") or "").strip(), timeout=timeout,
                   reference_mode=get("REFERENCE_MODE"), references=path("REFERENCES"), camera=get("CAMERA", "web"),
                   native_config=path("CONFIG"), native_binding=path("NATIVE_BINDING"))

    def configured(self):
        if self.backend == "dummy":
            return True
        entry = "mask.py" if self.stage == "segment" else "cot.py"
        if self.backend in ("native", "real"):
            return bool(self.repository and (self.repository / entry).is_file()
                        and self.python and self.python.is_file() and self.python.suffix.lower() not in (".bat", ".cmd", ".ps1")
                        and self.native_config and self.native_config.is_file()
                        and self.native_binding and self.native_binding.is_file())
        return bool(self.backend == "experimental" and self.repository and (self.repository / entry).is_file()
                    and (self.repository / "config/config.yaml").is_file()
                    and self.python and self.python.is_file()
                    and self.python.suffix.lower() not in (".bat", ".cmd", ".ps1")
                    and self.api_key and self.reference_mode in ("none", "fixed")
                    and (self.reference_mode != "fixed" or (self.references and self.references.is_file()))
                    and self.camera in ("web", "B", "F", "L", "R", "S1", "S2", "S3", "S4", "T"))
