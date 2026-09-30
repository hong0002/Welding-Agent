import json
import numpy as np

from backend.model_clients.centerline import component_paths
from backend.model_clients.contracts import ModelFault, ModelArtifact, Provenance
from backend.model_clients.runtime import ModelRuntime
from backend.schemas import Point2D, RoughTrajectory, TrajectorySegment


class VlmTrajectoryClient:
    def __init__(self, runtime: ModelRuntime):
        self.runtime = runtime

    def predict(self, image, mask, instruction, components, *, language=""):
        if not self.runtime.settings.configured():
            raise ModelFault("MODEL_NOT_CONFIGURED")
        paths = component_paths(components, instruction.region_order)
        # Both current raw language and backend-resolved constraints are explicit model inputs.
        context = (language or ("왼쪽에서 오른쪽으로 용접해" if instruction.direction == "left_to_right" else "오른쪽에서 왼쪽으로 용접해"))
        context += "\nBackend-confirmed selection: " + instruction.model_dump_json()
        context += "\nMask-to-region mapping: " + json.dumps({f"{self.runtime.settings.camera}:polyline_{i}": region
                                                               for i, region in enumerate(instruction.region_order)})
        context += "\nOnly the active masks are supplied, in the confirmed region_order. Exclusions have already been applied. Do not exclude again. Keep this order; weld each once."
        output = self.runtime.infer(image, {"instruction": context, "polylines": paths,
                                          "region_ids": instruction.region_order})
        try:
            trajectory = self.convert(output, image.size, instruction)
            trajectory.artifact = ModelArtifact(kind="rough", provenance=Provenance(
                artifact_id=output["artifact_id"],
                model_name=output["model_name"], model_version=output["model_version"],
                source_sha256=output["source_sha256"], latency_ms=output["latency_ms"],
                reference_mode=self.runtime.settings.reference_mode,
                reference_manifest_sha256=output.get("reference_manifest_sha256"),
                instruction=language, region_ids=instruction.region_order,
                input_transform="binary-skeleton-chain-v1 → external simplify_segments; pixels preserved"))
            return trajectory
        except Exception:
            self.runtime.last_error = "MODEL_OUTPUT_INVALID"
            raise ModelFault("MODEL_OUTPUT_INVALID") from None

    def convert(self, output, size, instruction):
        rough, plan, refined = output["rough_action"], output["plan"], output["refined_task"]
        camera = self.runtime.settings.camera
        regions = instruction.region_order
        ids = [f"segment_{i}" for i in range(len(regions))]
        masks = [f"{camera}:polyline_{i}" for i in range(len(regions))]
        segments = rough["segments"]
        def require(condition):
            if not condition:
                raise ValueError("output contract mismatch")
        require(rough["coordinate_frame"] == f"mask_normalized:{camera}" and rough["primary_camera"] == camera)
        require(plan["status"] == refined["status"] == "ready")
        require(len(refined["target_mask_ids"]) == len(masks) and set(refined["target_mask_ids"]) == set(masks))
        require(len(plan["grounded_mask_ids"]) == len(masks) and set(plan["grounded_mask_ids"]) == set(masks))
        require([s["segment_id"] for s in segments] == ids)
        decisions = plan["segment_decisions"]
        require(len(decisions) == len(ids) and {d["segment_id"] for d in decisions} == set(ids))
        decisions = {d["segment_id"]: d for d in decisions}
        operations = plan["operations"]
        require([op["order"] for op in operations] == sorted({op["order"] for op in operations}))
        require(all(op.get("segment_id") is None or op["segment_id"] in ids for op in operations))
        follow = [op for op in operations if op["action"] == "follow_segment"]
        require([op["segment_id"] for op in follow] == ids and all(op["weld_enabled"] is True for op in follow))
        require(all(op["weld_enabled"] is False for op in operations if op["action"] != "follow_segment"))
        result = []
        for i, (segment, region) in enumerate(zip(segments, regions)):
            require(segment["source_mask_id"] == masks[i] and segment["connected_to_next"] is False)
            points = np.asarray(segment["points_pixel"], dtype=np.float64)
            normalized = np.asarray(segment["points_normalized"], dtype=np.float64)
            require(points.ndim == 2 and points.shape[1] == 2 and 2 <= len(points) <= 4096)
            require(np.isfinite(points).all() and normalized.shape == points.shape and np.isfinite(normalized).all())
            require(np.all(points >= 0) and np.all(points < np.asarray(size)))
            require(np.allclose(points / np.asarray(size), normalized, atol=1e-6, rtol=0))
            decision = decisions[ids[i]]
            require(decision["weld_enabled"] is True and decision["direction"] in ("forward", "reverse"))
            if decision["direction"] == "reverse":
                points = points[::-1]
            # A model cannot silently override the already-confirmed left/right constraint.
            if instruction.direction == "left_to_right":
                require(tuple(points[0]) < tuple(points[-1]))
            else:
                require(tuple(points[0]) > tuple(points[-1]))
            result.append(TrajectorySegment(segment_id=i, region_id=region,
                                           points=[Point2D(x=float(x), y=float(y)) for x, y in points]))
        return RoughTrajectory(segments=result, generator="vlm_trajectory:simplify_segments+semantic_plan")
