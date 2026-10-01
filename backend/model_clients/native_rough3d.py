"""Explicit vlm_trajectory2 client; the established Rough2D workflow stays the baseline."""
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from backend.model_clients.config import ROOT
from backend.model_clients.native import NativeRoughClient, read_json, read_native_result,provenance
from backend.model_clients.contracts import ModelArtifact
from backend.model_clients.trajectory_contracts import ReferenceTrajectory3D


NativeRough2DClient = NativeRoughClient


@dataclass(frozen=True)
class NativeRough3DResult:
    sample_id: str
    directory: Path
    image_guidance_2d: dict
    reference_trajectory_3d: ReferenceTrajectory3D
    plan: dict
    artifact: ModelArtifact | None = None


class NativeRough3DClient(NativeRoughClient):
    """Workflow module returning 2D guidance and a separate non-executable reference."""

    @staticmethod
    def load_saved(directory, sample_id):
        directory = Path(directory).resolve()
        allowed = (ROOT / ".cache", ROOT.parent / "vlm_trajectory2" / "outputs")
        if not any(directory.is_relative_to(p.resolve()) for p in allowed):
            raise ValueError("Rough3D result must be an owned or native output")
        plan = read_json(directory / "iteration_001/plan.json")
        data = read_native_result("rough3d", directory, sample_id, plan["raw_instruction_ko"])
        return NativeRough3DResult(sample_id, directory, data["image_guidance_2d"],
                                  ReferenceTrajectory3D.model_validate(data["rough_trajectory_3d"]), data["plan"])

    def run_session(self, mask_session, instruction):
        if self.runtime.settings.stage != "rough3d":
            raise ValueError("Dedicated rough3d runtime required")
        result = super().run_session(mask_session, instruction)
        saved = self.load_saved(result.directory, result.data["sample_id"])
        return NativeRough3DResult(saved.sample_id,saved.directory,saved.image_guidance_2d,
                                   saved.reference_trajectory_3d,saved.plan,
                                   ModelArtifact(kind="rough",provenance=provenance(result,"rough3d",instruction)))

    def predict(self, image, mask, instruction, components, *, language=""):
        session, _, proof = self.prepare_session(image, mask, components)
        metadata = mask.info.get("mask_artifact")
        self.approvals.verify(session, mask, metadata)
        result = self.run_session(session, language)
        self.approvals.verify(session, mask, metadata)
        result.artifact.provenance.approved_mask_session_id = UUID(proof['session_id'])
        result.artifact.provenance.native_source_artifact_id = UUID(proof['source_native_artifact_id'])
        result.artifact.provenance.input_mask_sha256 = proof['mask_pixels_sha256']
        result.artifact.provenance.region_ids = instruction.region_order
        return result
