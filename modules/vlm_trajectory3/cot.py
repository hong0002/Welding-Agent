#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
import yaml
from openai import AuthenticationError, OpenAI
from PIL import Image

from data import (
    AcceptedMaskSession,
    image_data_url,
    load_accepted_session,
    load_sample,
)
from prompts import (
    PLANNER_DEVELOPER_PROMPT,
    PLANNER_PROMPT_VERSION,
    REFINER_DEVELOPER_PROMPT,
    REFINER_PROMPT_VERSION,
)
from render import render_korean_markdown, render_vla_markdown
from retrieval_client import RetrievalConfig, retrieve_actions
from schemas import DetailedPlan, RefinedTask
from trajectory import mask_descriptor, serialize_points, simplify_segments
from yolo_client import prepare_yolo
from visualization import (
    save_action_plot,
    save_planning_review,
    save_plan_overlay,
    save_query_sheet,
    save_reference_sheet,
)


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = PROJECT_DIR / "config" / "config.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="검색 few-shot 기반 상세 용접 CoT·가궤적 생성")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--mask-session", type=Path)
    parser.add_argument("--sample-id", help="단독 실행할 샘플 ID; --mask-session 없으면 새 YOLO 추론")
    parser.add_argument("--instruction", help="사용자 작업 지시")
    parser.add_argument("--once", action="store_true", help="피드백 없이 한 번만 생성")
    return parser.parse_args()


def find_api_key(value) -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {"openai_api_key", "api_key", "openai"} and isinstance(item, str):
                if item.strip():
                    return item.strip()
        for item in value.values():
            found = find_api_key(item)
            if found:
                return found
    return None


def load_api_key(path: Path) -> tuple[str, str]:
    if path.is_file():
        key = find_api_key(json.loads(path.read_text(encoding="utf-8")))
        if key:
            return key, str(path)
    environment_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if environment_key:
        return environment_key, "OPENAI_API_KEY"
    raise SystemExit("OPENAI_API_KEY 환경변수 또는 설정된 keys.json의 API 키가 필요합니다")


def resolve_input(args: argparse.Namespace) -> AcceptedMaskSession:
    if args.mask_session:
        session = load_accepted_session(args.mask_session)
        if args.sample_id and args.sample_id != session.sample_id:
            raise ValueError("--sample-id와 이전 마스크 세션의 샘플이 다릅니다")
        return session
    sample_id = args.sample_id or input("Sample ID (새 YOLO, 마스크 없이 시작): ").strip()
    instruction = args.instruction or input("작업 지시: ").strip()
    if not sample_id or not instruction:
        raise ValueError("샘플 ID와 작업 지시가 필요합니다")
    return AcceptedMaskSession(Path(), sample_id, instruction, 0, {})


def build_query_image_guidance(session: AcceptedMaskSession, sample, config: dict) -> dict:
    priority = config["planning"]["primary_camera_priority"]
    available = session.polylines if session.polylines else sample.images
    primary = next((camera for camera in priority if camera in available and camera in sample.images), None)
    if primary is None:
        raise RuntimeError("가궤적 기준 카메라를 선택할 수 없습니다")
    with Image.open(sample.images[primary]) as image:
        width, height = image.size
    if not session.polylines:
        return {"schema_version": "welding-image-guidance-v1", "mask_available": False,
                "source": "images_and_yolo_workpiece_boxes_only", "primary_camera": primary,
                "image_size": {"width": width, "height": height},
                "coordinate_frame_pixel": f"image_pixel:{primary}",
                "coordinate_frame_normalized": f"image_normalized:{primary}", "segments": []}
    source_paths = [np.asarray(path, dtype=np.float64) for path in session.polylines[primary]]
    simplified, budget = simplify_segments(source_paths, int(config["rough_trajectory"]["target_points"]))
    segments = []
    for index, points in enumerate(simplified):
        normalized = points / np.asarray([width, height], dtype=np.float64)
        segments.append(
            {
                "segment_id": f"segment_{index}",
                "source_mask_id": f"{primary}:polyline_{index}",
                "connected_to_next": False,
                "points_pixel": serialize_points(points),
                "points_normalized": serialize_points(normalized, digits=6),
            }
        )
    return {
        "schema_version": "welding-image-guidance-v1",
        "mask_available": True,
        "coordinate_frame_pixel": f"image_pixel:{primary}",
        "coordinate_frame_normalized": f"image_normalized:{primary}",
        "primary_camera": primary,
        "image_size": {"width": width, "height": height},
        **budget,
        "segments": segments,
    }


def select_reference_trajectory_3d(results: list[dict], query_segment_count: int | None) -> dict:
    """Select one retrieved H5 action as a start-relative 3D motion template.

    The query mask does not provide a calibrated image-to-robot transform.  Therefore the
    selected teaching path remains explicitly a reference-frame template instead of being
    mislabeled as the query sample's executable TCP coordinates.
    """
    if not results:
        raise RuntimeError("3D 가궤적으로 사용할 검색 teaching action이 없습니다")
    matching = [
        item
        for item in results
        if len(item.get("rough_action", {}).get("segments", [])) == query_segment_count
    ]
    selected = matching[0] if matching else results[0]
    method = (
        "highest_ranked_matching_segment_count"
        if matching
        else "highest_ranked_fallback_segment_count_mismatch"
    )
    if query_segment_count is None:
        method = "highest_ranked_no_query_mask"
    action = selected["rough_action"]
    segments = []
    for index, source in enumerate(action["segments"]):
        segments.append(
            {
                "segment_id": f"reference_segment_{index}",
                "source_segment_id": source["segment_id"],
                "connected_to_next": bool(source.get("connected_to_next", False)),
                "source_point_count": int(source["source_point_count"]),
                "source_length_mm": float(source["source_length_mm"]),
                "teaching_direction": source.get("direction", "unknown"),
                "teaching_direction_ko": source.get("direction_ko", ""),
                "teaching_direction_en": source.get("direction_en", ""),
                "points_xyz_mm": source["points_start_relative_mm"],
            }
        )
    return {
        "schema_version": "welding-reference-trajectory-3d-v1",
        "source_sample_id": selected["sample_id"],
        "selection_method": method,
        "coordinate_frame": "retrieved_teaching_start_relative",
        "source_coordinate_frame": action.get("coordinate_frame", "source_start_relative_mm"),
        "unit": "mm",
        "registered_to_query": False,
        "target_point_count": int(action["target_point_count"]),
        "actual_point_count": int(action["actual_point_count"]),
        "source_trajectory": selected.get("source_trajectory", {}),
        "segments": segments,
    }


def query_mask_ids(session: AcceptedMaskSession) -> list[str]:
    return [
        f"{camera}:polyline_{index}"
        for camera, paths in session.polylines.items()
        for index in range(len(paths))
    ]


def refine_instruction(
    client: OpenAI,
    model: str,
    effort: str,
    session: AcceptedMaskSession,
    sample,
    instruction: str,
    query_sheet: Path,
    detections: dict,
) -> tuple[RefinedTask, str]:
    ids = query_mask_ids(session)
    text = (
        "<query>\n"
        f"<sample_id>{escape(session.sample_id)}</sample_id>\n"
        f"<verified_sample_metadata>{escape(json.dumps(sample.metadata, ensure_ascii=False))}</verified_sample_metadata>\n"
        f'<raw_user_instruction language="ko">{escape(instruction)}</raw_user_instruction>\n'
        f"<approved_mask_ids>{escape(json.dumps(ids, ensure_ascii=False))}</approved_mask_ids>\n"
        f"<mask_available>{str(bool(ids)).lower()}</mask_available>\n"
        f"<visualization>{'Red overlays are approved predicted masks.' if ids else 'Cyan boxes identify workpieces only. NO query mask or seam coordinates are supplied.'} Multiple views can show the same joint.</visualization>\n"
        f"<workpiece_detections>{escape(json.dumps({k: {'width': v['width'], 'height': v['height'], 'boxes': v['boxes']} for k, v in detections['cameras'].items()}))}</workpiece_detections>\n"
        "</query>"
    )
    response = client.responses.parse(
        model=model,
        reasoning={"effort": effort},
        input=[
            {"role": "developer", "content": [{"type": "input_text", "text": REFINER_DEVELOPER_PROMPT}]},
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": text},
                    {"type": "input_image", "image_url": image_data_url(query_sheet), "detail": "high"},
                ],
            },
        ],
        text_format=RefinedTask,
    )
    if response.output_parsed is None:
        raise RuntimeError(f"지시 리파이너가 구조화된 결과를 반환하지 않았습니다: {response.output_text}")
    if set(response.output_parsed.target_mask_ids) - set(ids):
        raise RuntimeError("리파이너가 제공되지 않은 마스크 ID를 반환했습니다")
    return response.output_parsed, response.id


def prepare_reference_assets(results: list[dict], data_root: Path, cameras: list[str], output: Path, width: int):
    prepared = []
    for rank, item in enumerate(results, 1):
        sample = load_sample(data_root, item["sample_id"])
        sample_dir = output / f"{rank:02d}_{item['sample_id']}"
        sheet = save_reference_sheet(sample, cameras, sample_dir / "mask_views.jpg", width)
        action_plot = save_action_plot(item["rough_action"], sample_dir / "rough_action.jpg")
        prepared.append({"item": item, "sheet": sheet, "action_plot": action_plot})
    return prepared


def generate_plan(
    client: OpenAI,
    model: str,
    effort: str,
    refined: RefinedTask,
    image_guidance: dict,
    reference_trajectory_3d: dict,
    query_sheet: Path,
    references: list[dict],
    previous: DetailedPlan | None,
    feedback: str | None,
) -> tuple[DetailedPlan, str]:
    content = []
    for rank, reference in enumerate(references, 1):
        item = reference["item"]
        reference_text = {
            "rank": rank,
            "sample_id": item["sample_id"],
            "metadata": item["metadata"],
            "task_text_ko": item["texts"]["task_text_ko"],
            "action_text_ko": item["texts"]["action_text_ko"],
            "task_text_en": item["texts"]["task_text_en"],
            "action_text_en": item["texts"]["action_text_en"],
            "available_mask_views": item["mask"]["available_views"],
            "rough_action": item["rough_action"],
        }
        content.extend(
            [
                {"type": "input_text", "text": f"<reference_example>\n{json.dumps(reference_text, ensure_ascii=False)}"},
                {"type": "input_image", "image_url": image_data_url(reference["sheet"]), "detail": "high"},
                {"type": "input_image", "image_url": image_data_url(reference["action_plot"]), "detail": "high"},
                {"type": "input_text", "text": "</reference_example>"},
            ]
        )
    query = {
        "refined_task": refined.model_dump(),
        "valid_mask_ids": refined.target_mask_ids,
        "query_image_guidance_2d": image_guidance,
        "selected_reference_trajectory_3d": reference_trajectory_3d,
        "mask_available": image_guidance.get("mask_available", True),
        "valid_segment_ids": [segment["segment_id"] for segment in (
            image_guidance["segments"] if image_guidance.get("mask_available", True)
            else reference_trajectory_3d["segments"])],
    }
    if previous is not None and feedback:
        query["previous_plan"] = previous.model_dump()
        query["user_feedback_ko"] = feedback
        query["revision_instruction"] = "Revise the plan to satisfy the feedback while keeping valid IDs."
    content.extend(
        [
            {"type": "input_text", "text": f"<query>\n{json.dumps(query, ensure_ascii=False)}"},
            {"type": "input_image", "image_url": image_data_url(query_sheet), "detail": "high"},
            {"type": "input_text", "text": "</query>"},
        ]
    )
    response = client.responses.parse(
        model=model,
        reasoning={"effort": effort},
        input=[
            {"role": "developer", "content": [{"type": "input_text", "text": PLANNER_DEVELOPER_PROMPT}]},
            {"role": "user", "content": content},
        ],
        text_format=DetailedPlan,
    )
    plan = response.output_parsed
    if plan is None:
        raise RuntimeError(f"플래너가 구조화된 결과를 반환하지 않았습니다: {response.output_text}")
    if set(plan.grounded_mask_ids) - set(refined.target_mask_ids):
        raise RuntimeError("플래너가 제공되지 않은 마스크 ID를 반환했습니다")
    if plan.status == "needs_clarification":
        return plan, response.id
    valid_segments = set(query["valid_segment_ids"])
    decision_segments = {item.segment_id for item in plan.segment_decisions}
    invalid = decision_segments - valid_segments
    if invalid:
        raise RuntimeError(f"플래너가 존재하지 않는 segment를 반환했습니다: {sorted(invalid)}")
    missing = valid_segments - decision_segments
    if missing:
        raise RuntimeError(f"플래너가 segment 결정을 누락했습니다: {sorted(missing)}")
    invalid_operations = {
        item.segment_id
        for item in plan.operations
        if item.segment_id is not None and item.segment_id not in valid_segments
    }
    if invalid_operations:
        raise RuntimeError(f"작업 순서에 존재하지 않는 segment가 있습니다: {sorted(invalid_operations)}")
    return plan, response.id


def main() -> None:
    args = parse_args()
    config = yaml.safe_load(args.config.expanduser().read_text(encoding="utf-8"))
    session = resolve_input(args)
    instruction = args.instruction or session.instruction
    data_root = Path(config["data"]["root"]).expanduser().resolve()
    sample = load_sample(data_root, session.sample_id)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output_root = Path(config["output"]["root"]).expanduser().resolve()
    output = output_root / f"{timestamp}_{session.sample_id}"
    output.mkdir(parents=True, exist_ok=False)
    detections = prepare_yolo(config, sample, output / "yolo", session.path if args.mask_session else None)
    line_width = int(config["planning"]["mask_line_width_px"])
    query_sheet = save_query_sheet(sample, session.polylines, output / "query_views.jpg", line_width, detections)
    image_guidance = build_query_image_guidance(session, sample, config)
    (output / "query_image_guidance_2d.json").write_text(
        json.dumps(image_guidance, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    key_path = Path(config["models"]["api_keys_path"]).expanduser()
    api_key, key_source = load_api_key(key_path)
    client = OpenAI(api_key=api_key)
    refiner_model = str(config["models"]["refiner"])
    planner_model = str(config["models"]["planner"])
    effort = str(config["models"].get("reasoning_effort", "medium"))
    print(f"[OPENAI] refiner={refiner_model}, planner={planner_model}, key_source={key_source}")

    try:
        print(f"[REFINE] sample={session.sample_id}, prompt={REFINER_PROMPT_VERSION}")
        refined, refiner_response_id = refine_instruction(
            client, refiner_model, effort, session, sample, instruction, query_sheet, detections
        )
    except AuthenticationError as exc:
        raise SystemExit(
            f"OpenAI 인증 실패(401): key_source={key_source}. 유효한 프로젝트 API 키로 교체하세요."
        ) from exc

    while refined.status == "needs_clarification":
        (output / "refiner.json").write_text(
            json.dumps(refined.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if args.once:
            print(f"[CLARIFY] {refined.clarification_question_ko}")
            return
        answer = input(f"추가 확인: {refined.clarification_question_ko}\n답변: ").strip()
        if not answer:
            continue
        instruction = f"{instruction}\n추가 답변: {answer}"
        refined, refiner_response_id = refine_instruction(
            client, refiner_model, effort, session, sample, instruction, query_sheet, detections
        )

    (output / "refiner.json").write_text(
        json.dumps(
            {"prompt_version": REFINER_PROMPT_VERSION, "response_id": refiner_response_id, **refined.model_dump()},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    image_sizes = {}
    for camera, path in sample.images.items():
        with Image.open(path) as image:
            image_sizes[camera] = image.size
    descriptor = mask_descriptor(session.polylines, image_sizes) if session.polylines else None
    weights = dict(config["retrieval"]["weights"])
    if not session.polylines:
        weights["mask_shape"] = 0.0
    retrieval_payload = {
        "sample_id": session.sample_id,
        "refined_search_text_ko": refined.search_text_ko,
        "accepted_masks": session.polylines,
        "mask_available": bool(session.polylines),
        "query_manifest": detections["manifest_path"],
        "mask_descriptor": descriptor,
        "top_k": int(config["retrieval"]["top_k"]),
        "candidate_pool": int(config["retrieval"]["candidate_pool"]),
        "rrf_constant": int(config["retrieval"]["rrf_constant"]),
        "weights": weights,
    }
    server = RetrievalConfig(
        ssh_alias=config["server"]["ssh_alias"],
        remote_root=config["server"]["remote_root"],
        remote_python=config["server"]["remote_python"],
    )
    print(f"[RETRIEVE] image+text{' + mask' if session.polylines else ' (no mask)'} sample={session.sample_id}")
    retrieval = retrieve_actions(server, retrieval_payload)
    (output / "retrieval.json").write_text(
        json.dumps(retrieval, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    reference_ids = [item["sample_id"] for item in retrieval.get("results", [])]
    print(f"[RETRIEVED] {', '.join(reference_ids)}")
    references = prepare_reference_assets(
        retrieval.get("results", []),
        data_root,
        list(session.polylines) if session.polylines else list(sample.images),
        output / "references",
        line_width,
    )
    if not references:
        raise RuntimeError("GPT에 제공할 reference action이 없습니다")
    reference_trajectory_3d = select_reference_trajectory_3d(
        retrieval.get("results", []), len(image_guidance["segments"]) if session.polylines else None
    )
    (output / "reference_trajectory_3d.json").write_text(
        json.dumps(reference_trajectory_3d, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        "[3D REFERENCE] "
        f"sample={reference_trajectory_3d['source_sample_id']}, "
        f"points={reference_trajectory_3d['actual_point_count']}, "
        f"frame={reference_trajectory_3d['coordinate_frame']}"
    )

    previous = None
    feedback = None
    iteration = 1
    while True:
        print(f"[GPT] iteration={iteration}, references={len(references)}, prompt={PLANNER_PROMPT_VERSION}")
        try:
            plan, planner_response_id = generate_plan(
                client,
                planner_model,
                effort,
                refined,
                image_guidance,
                reference_trajectory_3d,
                query_sheet,
                references,
                previous,
                feedback,
            )
        except AuthenticationError as exc:
            raise SystemExit(
                f"OpenAI 인증 실패(401): key_source={key_source}. 유효한 프로젝트 API 키로 교체하세요."
            ) from exc
        iteration_dir = output / f"iteration_{iteration:03d}"
        iteration_dir.mkdir(parents=True)
        if plan.status == "needs_clarification":
            (iteration_dir / "clarification.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")
            question = plan.clarification_question_ko or "작업할 접합부와 진행 방향을 더 구체적으로 알려주세요."
            if args.once:
                print(f"[CLARIFY] {question}")
                return
            answer = input(f"추가 확인: {question}\n답변: ").strip()
            if not answer:
                raise SystemExit("작업 대상이 확정되지 않아 중단했습니다")
            previous, feedback = plan, answer
            iteration += 1
            continue
        combined = {
            "schema_version": "welding-cot-v3",
            "sample_id": session.sample_id,
            "mask_available": bool(session.polylines),
            "previous_mask_session": str(session.path) if args.mask_session else None,
            "yolo_request_id": detections["request_id"],
            "raw_instruction_ko": instruction,
            "refiner_prompt_version": REFINER_PROMPT_VERSION,
            "planner_prompt_version": PLANNER_PROMPT_VERSION,
            "refiner_response_id": refiner_response_id,
            "planner_response_id": planner_response_id,
            "refined_task": refined.model_dump(),
            "reference_sample_ids": reference_ids,
            "rough_trajectory_3d": reference_trajectory_3d,
            "image_guidance_2d": image_guidance,
            "plan": plan.model_dump(),
            "feedback": feedback,
        }
        (iteration_dir / "plan.json").write_text(
            json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (iteration_dir / "cot_ko.md").write_text(
            render_korean_markdown(
                plan, refined, reference_trajectory_3d, image_guidance, reference_ids
            ),
            encoding="utf-8",
        )
        (iteration_dir / "vla_prompt.md").write_text(
            render_vla_markdown(plan, refined, reference_trajectory_3d, image_guidance),
            encoding="utf-8",
        )
        directions = {item.segment_id: item.direction for item in plan.segment_decisions}
        overlay = save_plan_overlay(
            sample.images[image_guidance["primary_camera"]],
            image_guidance,
            directions,
            iteration_dir / "image_guidance_2d_overlay.jpg",
        ) if session.polylines else query_sheet
        trajectory_3d_plot = save_action_plot(
            reference_trajectory_3d, iteration_dir / "rough_trajectory_3d.jpg"
        )
        review = save_planning_review(overlay, trajectory_3d_plot, iteration_dir / "review_all.jpg")
        print(f"[VIEW] {review}")
        print(f"[2D VIEW] {overlay}")
        print(f"[3D VIEW] {trajectory_3d_plot}")
        print(f"[COT] {iteration_dir / 'cot_ko.md'}")
        print(f"[VLA] {iteration_dir / 'vla_prompt.md'}")
        if args.once:
            break
        answer = input("결과가 맞으면 ok, 수정할 내용이 있으면 피드백 입력: ").strip()
        if answer.lower() == "ok":
            (output / "status.json").write_text(
                json.dumps({"status": "ok", "accepted_iteration": iteration}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print("[OK] 상세 CoT와 가궤적을 확정했습니다")
            break
        if not answer:
            continue
        previous = plan
        feedback = answer
        iteration += 1


if __name__ == "__main__":
    main()
