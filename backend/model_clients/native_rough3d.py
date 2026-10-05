from backend.services.project_paths import native_parent
"""Explicit vlm_trajectory2 client; the established Rough2D workflow stays the baseline."""
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from backend.model_clients.config import ROOT
from backend.model_clients.native import NativeRoughClient, read_json, read_native_result,provenance
from backend.model_clients.contracts import ModelArtifact
from backend.model_clients.trajectory_contracts import ReferenceTrajectory3D
from backend.model_clients.native_profiles import native_profile


NativeRough2DClient = NativeRoughClient


@dataclass(frozen=True)
class NativeRough3DResult:
    sample_id: str
    directory: Path
    image_guidance_2d: dict
    reference_trajectory_3d: ReferenceTrajectory3D
    plan: dict
    artifact: ModelArtifact | None = None
    native_stack: str = 'vlm_trajectory2'


class NativeRough3DClient(NativeRoughClient):
    """Workflow module returning 2D guidance and a separate non-executable reference."""

    @staticmethod
    def load_saved(directory, sample_id, *, version=None):
        directory = Path(directory).resolve()
        allowed = (ROOT / ".cache", native_parent(ROOT) / "vlm_trajectory2" / "outputs", native_parent(ROOT)/'vlm_trajectory3/outputs')
        if not any(directory.is_relative_to(p.resolve()) for p in allowed):
            raise ValueError("Rough3D result must be an owned or native output")
        plan = read_json(directory / "iteration_001/plan.json")
        actual = ('native_3d_v3' if plan.get('planner_prompt_version') == 'welding-detailed-plan-v3-optional-mask'
                  else 'native_3d_v2')
        if version is not None and version != actual:
            raise ValueError('Rough3D native version differs')
        data = read_native_result("rough3d", directory, sample_id, plan["raw_instruction_ko"], version=actual)
        return NativeRough3DResult(sample_id, directory, data["image_guidance_2d"],
                                  ReferenceTrajectory3D.model_validate(data["rough_trajectory_3d"]), data["plan"],
                                  native_stack='vlm_trajectory3' if actual == 'native_3d_v3' else 'vlm_trajectory2')

    def run_session(self, mask_session, instruction):
        if self.runtime.settings.stage != "rough3d":
            raise ValueError("Dedicated rough3d runtime required")
        result = super().run_session(mask_session, instruction)
        saved = self.load_saved(result.directory, result.data["sample_id"],
                                version=native_profile(self.runtime.settings.stage,self.runtime.settings.backend).name)
        return NativeRough3DResult(saved.sample_id,saved.directory,saved.image_guidance_2d,
                                   saved.reference_trajectory_3d,saved.plan,
                                   ModelArtifact(kind="rough",provenance=provenance(result,"rough3d",instruction)),saved.native_stack)

    def predict(self, image, mask, instruction, components, *, language=""):
        session, _, proof = self.prepare_session(image, mask, components,region_order=instruction.region_order)
        metadata = mask.info.get("mask_artifact")
        self.approvals.verify(session, mask, metadata)
        result = self.run_session(session, language)
        self.approvals.verify(session, mask, metadata)
        result.artifact.provenance.approved_mask_session_id = UUID(proof['session_id'])
        result.artifact.provenance.native_source_artifact_id = UUID(proof['source_native_artifact_id'])
        result.artifact.provenance.input_mask_sha256 = proof['mask_pixels_sha256']
        result.artifact.provenance.region_ids = instruction.region_order
        return result


NativeRough3DV2Client = NativeRough3DClient


class NativeRough3DV3Client(NativeRough3DClient):
    def prepare_session(self, image, mask, components, *, region_order=None):
        binding = self.runtime.binding(image)
        return self.approvals.prepare(binding, mask, mask.info.get('mask_artifact'), components, carry_yolo=True,region_order=region_order)
