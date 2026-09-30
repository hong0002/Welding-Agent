"""Uses the external module's actual query simplifier, refiner, and semantic planner."""
import importlib
from pathlib import Path


def predict(request, directory: Path, client, config, references):
    module = importlib.import_module("cot")
    data = importlib.import_module("data")
    camera = request["camera"]
    # No claimed physical camera, dataset categories, query GT, approval file or robot pose.
    sample = data.SampleData("web_query", {camera: directory / "image.png"}, {}, {})
    session = data.AcceptedMaskSession(directory, "web_query", request["instruction"], 1,
                                       {camera: request["polylines"]})
    # Only routing changes: use this uploaded view. Keep external point budget and simplifier.
    config = {**config, "planning": {**config["planning"], "primary_camera_priority": [camera]}}
    rough = module.build_query_rough_action(session, sample, config)
    sheet = module.save_query_sheet(sample, session.polylines, directory / "query_masks.jpg",
                                    int(config["planning"]["mask_line_width_px"]))
    settings = config["models"]
    refined, _ = module.refine_instruction(client, settings["refiner"], settings["reasoning_effort"],
                                            session, sample, request["instruction"], sheet)
    if refined.status != "ready":
        from backend.model_clients.contracts import ModelFault
        raise ModelFault("MODEL_INPUT_INVALID")
    plan, _ = module.generate_plan(client, settings["planner"], settings["reasoning_effort"],
                                   refined, rough, sheet, references, None, None)
    return {"model_name": settings["planner"], "model_version": module.PLANNER_PROMPT_VERSION,
            "refiner_model": settings["refiner"], "refiner_version": module.REFINER_PROMPT_VERSION,
            "rough_action": rough, "refined_task": refined.model_dump(), "plan": plan.model_dump()}
