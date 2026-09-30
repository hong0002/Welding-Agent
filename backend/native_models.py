"""Offline native preflight/artifact comparison, or explicit one-sample native CLI run."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from backend.model_clients.config import ModelSettings
from backend.model_clients.contracts import ModelFault
from backend.model_clients.native import NativeRuntime, NativeSegmentClient, NativeRoughClient, read_json, sha256
from backend.services.components import detect_components


def content_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def summarize(stage, directory):
    directory = Path(directory).resolve()
    iteration = directory / "iteration_001"
    retrieval = read_json(directory / "retrieval.json")
    summary = {"sample_id": retrieval["query_sample_id"],
               "retrieved_ids": [item["sample_id"] for item in retrieval["results"]],
               "retrieval_sha256": content_hash(retrieval),
               "filenames": sorted(str(p.relative_to(directory)).replace("\\", "/") for p in directory.rglob("*") if p.is_file()),
               "reference_files": {str(p.relative_to(directory)).replace("\\", "/"): sha256(p)
                                   for base in (directory / "fewshots", directory / "references")
                                   for p in sorted(base.rglob("*")) if p.is_file()}}
    if stage == "segment":
        data = read_json(iteration / "result.json")
        summary.update(instruction=data["instruction"], prompt_version=data["prompt_version"],
                       parsed_predictions_sha256=content_hash(data["predictions"]), masks={})
        for camera in data["predictions"]:
            with Image.open(iteration / f"{camera}_prediction.png") as mask:
                values = np.unique(mask).tolist()
                binary = mask.mode == "L" and set(values) <= {0, 255}
                counts = ({"regions_min_area_1": len(detect_components(mask, 1).regions),
                           "regions_min_area_16": len(detect_components(mask, 16).regions)}
                          if binary and np.any(mask) else {})
                summary["masks"][camera] = {"mode": mask.mode, "size": list(mask.size), "values": values,
                                            "binary": binary, "pixel_sha256": hashlib.sha256(mask.tobytes()).hexdigest(), **counts}
    else:
        data = read_json(iteration / "plan.json")
        rough = data["rough_trajectory"]
        summary.update(instruction=data["raw_instruction_ko"],
                       refiner_prompt_version=data["refiner_prompt_version"], planner_prompt_version=data["planner_prompt_version"],
                       refined_instruction_sha256=content_hash(data["refined_task"]),
                       semantic_plan_sha256=content_hash(data["plan"]),
                       rough_action_sha256=content_hash(read_json(directory / "query_rough_action.json")),
                       plan_rough_sha256=content_hash(rough),
                       pixel_points=[s["points_pixel"] for s in rough["segments"]],
                       normalized_points=[s["points_normalized"] for s in rough["segments"]],
                       segment_count=len(rough["segments"]),
                       markdown={name: sha256(iteration / name) for name in ("cot_ko.md", "vla_prompt.md")})
    return summary


def compare(stage, native, adapter):
    if Path(native).resolve() == Path(adapter).resolve():
        raise ValueError("Two distinct A/B output directories are required")
    a, b = summarize(stage, native), summarize(stage, adapter)
    checks = {key: a[key] == b[key] for key in a}
    return {"scope": "saved_native_artifact_comparison", "live_called": False,
            "stage": stage, "checks": checks, "all_equal": all(checks.values()),
            "semantic_review_required": not all(checks.values()), "A": a, "B": b}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "run", "compare"))
    parser.add_argument("stage", choices=("segment", "rough"))
    parser.add_argument("--live", action="store_true", help="Invoke original CLI, SSH retrieval and paid OpenAI requests")
    parser.add_argument("--sample-id")
    parser.add_argument("--instruction")
    parser.add_argument("--views", nargs="+")
    parser.add_argument("--mask-session", type=Path)
    parser.add_argument("--native-output", type=Path)
    parser.add_argument("--adapter-output", type=Path)
    args = parser.parse_args()
    runtime = NativeRuntime(ModelSettings.from_env(args.stage))
    try:
        if args.action == "compare":
            if not args.native_output or not args.adapter_output:
                parser.error("compare requires --native-output and --adapter-output")
            report = compare(args.stage, args.native_output, args.adapter_output)
        elif args.action == "check":
            report = {"live_called": False, "web_status": runtime.status()}
            try:
                runtime.configuration()
                report["native_cli_configured"] = True
            except ModelFault as exc:
                report.update(native_cli_configured=False, code=exc.code)
            report["remote_readiness"] = "unverified; no SSH, API or dataset traversal"
        else:
            if not args.live or not args.instruction:
                parser.error("run requires --live and --instruction")
            if args.stage == "segment":
                if not args.sample_id or args.mask_session:
                    parser.error("segment requires --sample-id, no --mask-session")
                result = NativeSegmentClient(runtime).run_sample(args.sample_id, args.instruction, views=args.views)
            else:
                if not args.mask_session or args.sample_id or args.views:
                    parser.error("rough requires --mask-session, no --sample-id/--views")
                result = NativeRoughClient(runtime).run_session(args.mask_session, args.instruction)
            report = {"native_output": str(result.directory), "artifact_id": result.artifact_id,
                      "latency_ms": result.latency_ms, "summary": summarize(args.stage, result.directory)}
        print(json.dumps(report, ensure_ascii=True, indent=2))
        return 0
    except ModelFault as exc:
        print(json.dumps({"code": exc.code, "message": exc.message}, ensure_ascii=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
