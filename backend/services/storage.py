import json
import os
from pathlib import Path
from threading import RLock
from uuid import UUID, uuid4

from PIL import Image

from backend.orchestrator.state_machine import WorkflowError
from backend.schemas import WeldJob
from backend.services.legacy_migration import upgrade_legacy_job


class LocalStorage:
    """Single-process local MVP store; immutable artifacts + atomic job snapshots."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.lock = RLock()
        for folder in ("scenes", "masks", "trajectories", "jobs", "native_context"):
            (self.root / folder).mkdir(parents=True, exist_ok=True)

    def artifact_path(self, folder: str, artifact_id: UUID, suffix: str = ".png") -> Path:
        # IDs are typed UUIDs at every public entry point; filenames never come from uploads.
        return self.root / folder / f"{artifact_id}{suffix}"

    def save_image(self, folder: str, artifact_id: UUID, image: Image.Image, suffix: str = ".png") -> None:
        image.save(self.artifact_path(folder, artifact_id, suffix), format="PNG")

    def read_image(self, folder: str, artifact_id: UUID) -> Image.Image:
        with Image.open(self.artifact_path(folder, artifact_id)) as image:
            return image.copy()

    def save_job(self, job: WeldJob) -> None:
        self._write_json(self.artifact_path("jobs", job.id, ".json"), job.model_dump_json(indent=2))

    def save_trajectories(self, job: WeldJob) -> None:
        # This file is a convenient preview export; the job snapshot remains authoritative.
        payload = {
            "job_id": str(job.id), "schema_version": 2, "preview_only": True,
            "rough_trajectory": job.rough_trajectory.model_dump(mode="json") if job.rough_trajectory else None,
            "final_trajectory": job.final_trajectory.model_dump(mode="json") if job.final_trajectory else None,
            "validation": job.validation.model_dump(mode="json") if job.validation else None,
        }
        self._write_json(self.artifact_path("trajectories", job.id, ".json"), json.dumps(payload, indent=2))

    @staticmethod
    def _write_json(path: Path, payload: str) -> None:
        temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(payload, encoding="utf-8")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def get_job(self, job_id: UUID) -> WeldJob:
        path = self.artifact_path("jobs", job_id, ".json")
        if not path.is_file():
            raise WorkflowError("Job not found.", 404)
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw)
        if payload.get("schema_version", 1) == 1:
            mask = payload.get("mask")
            mask_image = self.read_image("masks", UUID(mask["id"])) if mask else None
            job = upgrade_legacy_job(payload, mask_image)
            backup = self.artifact_path("jobs", job_id, ".legacy-v1.json")
            if not backup.exists():
                self._write_json(backup, raw)
            self.save_trajectories(job)
            self.save_job(job)
            return job
        return WeldJob.model_validate(payload)
