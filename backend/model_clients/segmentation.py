from PIL import Image

from backend.model_clients.contracts import ModelFault, Provenance
from backend.model_clients.runtime import ModelRuntime
from backend.services.mask_service import validate_binary_mask


class RealVlmSegmentationClient:
    def __init__(self, runtime: ModelRuntime):
        self.runtime = runtime

    def segment(self, image: Image.Image, *, instruction: str = "용접할 영역을 찾아주세요.") -> Image.Image:
        output = self.runtime.infer(image, {"instruction": instruction})
        try:
            with Image.open(output["artifact_directory"] / "mask.png") as source:
                mask = source.copy()
            validate_binary_mask(mask, image.size)
            mask.info["model_provenance"] = Provenance(
                artifact_id=output["artifact_id"],
                model_name=output["model_name"], model_version=output["model_version"],
                source_sha256=output["source_sha256"], latency_ms=output["latency_ms"],
                reference_mode=self.runtime.settings.reference_mode,
                reference_manifest_sha256=output.get("reference_manifest_sha256"), instruction=instruction,
                input_transform="vlm_segment.prediction_paths+rasterize-v1")
            return mask
        except Exception:
            self.runtime.last_error = "MODEL_OUTPUT_INVALID"
            raise ModelFault("MODEL_OUTPUT_INVALID") from None
