"""Fixed integration entry point; imports external functions, never their CLI main()."""
import importlib
import json
import logging
import os
import sys
from pathlib import Path


def references(request, stage):
    if request["reference_mode"] == "none":
        return []
    path = Path(request["references"])
    if path.stat().st_size > 4_000_000:
        raise ValueError("reference manifest too large")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest["schema_version"] != 1 or manifest["stage"] != stage or manifest["camera"] != request["camera"]:
        raise ValueError("reference contract mismatch")
    items = manifest["examples"]
    if not 1 <= len(items) <= 3:
        raise ValueError("one to three explicit references required")
    def file(value):
        resolved = (path.parent / value).resolve()
        if not resolved.is_file():
            raise ValueError("reference file missing")
        return resolved
    if stage == "segment":
        return [(item["sample_id"], file(item["original"]), file(item["overlay"])) for item in items]
    return [{"item": item["item"], "sheet": file(item["sheet"]), "action_plot": file(item["action_plot"])} for item in items]


def segment(request, directory, client, config):
    import math
    from PIL import Image
    module = importlib.import_module("mask")
    data = importlib.import_module("mask_data")
    settings = config["mask"]
    prediction, _response_id = module.predict_camera(
        client, settings["model"], settings["reasoning_effort"], "web_query", request["instruction"],
        request["camera"], directory / "image.png", references(request, "segment"), None, None)
    with Image.open(directory / "image.png") as image:
        width, height = image.size
    paths = module.prediction_paths(prediction)
    if not paths or len(paths) > 256 or len(paths) != len(prediction.polylines):
        raise ValueError("invalid polylines")
    for points in paths:
        if not 2 <= len(points) <= 4096 or len({tuple(point) for point in points}) < 2:
            raise ValueError("degenerate polyline")
        if any(not math.isfinite(x) or not math.isfinite(y) or not 0 <= x < width or not 0 <= y < height for x, y in points):
            raise ValueError("coordinates outside original image")
    line_width = int(settings["line_width_px"])
    if not 1 <= line_width <= 256:
        raise ValueError("invalid raster width")
    data.rasterize((width, height), paths, line_width).save(directory / "mask.png")
    return {"model_name": settings["model"], "model_version": module.PROMPT_VERSION,
            "polylines": paths, "line_width_px": line_width, "camera": request["camera"]}


def rough(request, directory, client, config):
    # Filled by the independent rough integration; no dummy substitution in this worker.
    from rough_worker import predict
    return predict(request, directory, client, config, references(request, "rough"))


def main():
    path = Path(sys.argv[1]).resolve()
    directory = path.parent
    output_path = directory / "output.json"
    try:
        request = json.loads(path.read_text(encoding="utf-8"))
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        sys.path.insert(0, request["repository"])
        import yaml
        from openai import OpenAI
        from backend.model_clients.integrity import source_digest
        for name in ("openai", "httpx", "httpcore"):
            logging.getLogger(name).setLevel(logging.CRITICAL)
        config = yaml.safe_load((Path(request["repository"]) / "config/config.yaml").read_text(encoding="utf-8"))
        with OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=request["timeout"], max_retries=0) as client:
            if request["stage"] == "segment":
                output = segment(request, directory, client, config)
            elif request["stage"] == "rough":
                output = rough(request, directory, client, config)
            else:
                raise ValueError("unsupported stage")
        output["source_sha256"] = source_digest(Path(request["repository"]))
        if request.get("references"):
            import hashlib
            output["reference_manifest_sha256"] = hashlib.sha256(Path(request["references"]).read_bytes()).hexdigest()
        output_path.write_text(json.dumps(output, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        return 0
    except Exception as exc:
        # Never print exception payloads, credentials, prompt text, paths or SDK responses.
        name = type(exc).__name__
        if name == "ModelFault":
            code = exc.code
        elif name in ("APITimeoutError", "TimeoutError"):
            code = "MODEL_TIMEOUT"
        elif name in ("AuthenticationError", "PermissionDeniedError", "NotFoundError", "RateLimitError", "APIConnectionError", "ModuleNotFoundError"):
            code = "MODEL_NOT_READY"
        elif "out of memory" in str(exc).lower():
            code = "MODEL_OOM"
        elif name in ("ValueError", "ValidationError", "KeyError", "TypeError", "IndexError"):
            code = "MODEL_OUTPUT_INVALID"
        else:
            code = "MODEL_PROCESS_FAILED"
        output_path.write_text(json.dumps({"error": code}), encoding="utf-8")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
