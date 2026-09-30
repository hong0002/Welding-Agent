"""Experimental image-only smoke; native CLI uses backend.native_models instead."""
import argparse
import json
import time
from pathlib import Path

from backend.model_clients.config import ModelSettings
from backend.model_clients.contracts import ModelFault
from backend.model_clients.rough import VlmTrajectoryClient
from backend.model_clients.runtime import ModelRuntime
from backend.model_clients.segmentation import RealVlmSegmentationClient
from backend.orchestrator.region_selection import resolve_regions
from backend.schemas import Scene, StructuredInstruction
from backend.services.components import detect_components
from backend.services.mask_service import decode_image, validate_binary_mask
from backend.services.validation import DummyTrajectoryValidator
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("segment", "rough", "pipeline"))
    parser.add_argument("--live", action="store_true", help="Explicitly invoke paid remote VLM inference on this ONE image")
    parser.add_argument("--image", type=Path)
    parser.add_argument("--mask", type=Path, help="Required for rough; the exact confirmed binary PNG")
    parser.add_argument("--instruction", default="용접할 부분을 왼쪽에서 오른쪽으로 용접해")
    parser.add_argument("--direction", choices=("left_to_right", "right_to_left"), default="left_to_right")
    args = parser.parse_args()
    stages = ("segment", "rough") if args.stage == "pipeline" else (args.stage,)
    runtimes = {stage: ModelRuntime(ModelSettings.from_env(stage)) for stage in stages}
    if not args.live:
        print(json.dumps({"live_called": False, "models": {stage: runtime.status() for stage, runtime in runtimes.items()},
                          "vla": "deferred", "note": "Use --live with one image to explicitly run remote inference."}, ensure_ascii=False))
        return 0
    if not args.image or (args.stage == "rough" and not args.mask):
        parser.error("--live requires --image; rough also requires --mask")
    if any(runtime.settings.backend != "experimental" or not runtime.settings.configured() for runtime in runtimes.values()):
        print(json.dumps({"error": "MODEL_NOT_CONFIGURED", "live_called": False}))
        return 2
    started = time.monotonic()
    report = {"schema_version": 1, "scope": "segment_rough_only", "vla": "deferred", "is_robot_executable": False,
              "gpu_peak_memory_mb": None, "gpu_note": "Hosted inference; remote memory telemetry unavailable", "stages": {}}
    try:
        image = decode_image(args.image.read_bytes())
        if "segment" in stages:
            print("Segmentation: one remote prediction starting", flush=True)
            mask = RealVlmSegmentationClient(runtimes["segment"]).segment(image, instruction=args.instruction)
            components = detect_components(mask)
            report["stages"]["segment"] = {"latency_ms": mask.info["model_provenance"].latency_ms,
                                            "regions": len(components.regions), "width": mask.width, "height": mask.height}
            print("Segmentation: binary output validated", flush=True)
        else:
            mask = decode_image(args.mask.read_bytes(), mask=True)
            validate_binary_mask(mask, image.size)
            components = detect_components(mask)
        if "rough" in stages:
            print("Rough: one refiner + one planner call starting", flush=True)
            instruction = resolve_regions(StructuredInstruction(direction=args.direction), components.regions)
            rough = VlmTrajectoryClient(runtimes["rough"]).predict(image, mask, instruction, components, language=args.instruction)
            scene = Scene(id=uuid4(), width=image.width, height=image.height, image_url="smoke")
            validation = DummyTrajectoryValidator().validate(rough, scene, components=components,
                              expected_segments=list(enumerate(instruction.region_order)))
            if not validation.valid:
                raise ModelFault("MODEL_OUTPUT_INVALID")
            report["stages"]["rough"] = {"latency_ms": rough.artifact.provenance.latency_ms, "segments": len(rough.segments),
                                         "points": sum(len(s.points) for s in rough.segments), "frame": "image_pixel", "units": "px"}
            print("Rough: correspondence and preview geometry validated", flush=True)
        report["success"] = True
    except ModelFault as exc:
        report.update(success=False, code=exc.code, message=exc.message)
    except Exception:
        report.update(success=False, code="MODEL_INPUT_INVALID", message="Smoke 입력 이미지와 바이너리 마스크를 확인하세요.")
    report["total_latency_ms"] = (time.monotonic() - started) * 1000
    destination = Path(__file__).resolve().parents[1] / ".cache/models/smoke"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / f"{uuid4()}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
