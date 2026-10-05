#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
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
    parser.add_argument("--resume-session", type=Path, help="기존 세션 승인 결과부터 피드백 이어서 생성")
    parser.add_argument("--feedback", help="이어서 적용할 수정 지시")
    parser.add_argument("--sample-id", help="단독 실행할 샘플 ID; --mask-session 없으면 새 YOLO 추론")
    parser.add_argument("--instruction", help="사용자 작업 지시")
    endpoint_flags=parser.add_mutually_exclusive_group()
    endpoint_flags.add_argument("--no-end", action="store_true", help="기존 세션의 끝점 조건도 해제")
    endpoint_flags.add_argument("--end", action="store_true", help="현재 샘플 H5 시작·끝 XYZ를 가궤적 생성에 제공")
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
    endpoint: dict | None = None,
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
    if endpoint:
        query["endpoint_conditioning"] = endpoint
    if previous is not None:
        query["previous_plan"] = previous.model_dump()
    if feedback:
        query["user_feedback_ko"] = feedback
        query["revision_instruction"] = "Latest feedback overrides conflicting older task scope and previous plan. Update task summaries, operations and numeric draft together. Do not retain a two-sided task when the user requests one side."
    if not endpoint:
        query["endpoint_instruction"] = "No query endpoint constraint is supplied. Infer the end of the currently requested seam; do not preserve an old full-task endpoint."
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
            {"role": "developer", "content": [{"type": "input_text", "text": PLANNER_DEVELOPER_PROMPT + (
                "\nThe query supplies actual start/end XYZ in source robot mm. Generate the draft in these same axes, "
                "relative to known_start_xyz_mm: first point (0,0,0), last point known_end_offset_mm. "
                "Use the endpoint of the CURRENT query, not a retrieved example. Preserve requested multi-segment "
                "topology and estimate interior points from images and instructions. Do not request these endpoints again."
                if endpoint else "")}]},
            {"role": "user", "content": content},
        ],
        text_format=DetailedPlan,
    )
    plan = response.output_parsed
    if plan is None:
        raise RuntimeError(f"플래너가 구조화된 결과를 반환하지 않았습니다: {response.output_text}")
    if set(plan.grounded_mask_ids) - set(refined.target_mask_ids):
        raise RuntimeError("플래너가 제공되지 않은 마스크 ID를 반환했습니다")
    return plan, response.id


def generated_trajectory(plan, reference):
    segments=[]
    for item in plan.rough_segments:
        points=np.asarray([[p.x,p.y,p.z] for p in item.points],dtype=float)
        if not np.isfinite(points).all():
            raise ValueError("Non-finite draft XYZ")
        segments.append(dict(segment_id=item.segment_id,kind=item.kind,
                             points_xyz_mm=points.tolist(),connected_to_next=False,
                             teaching_direction="estimated",source_length_mm=float(np.linalg.norm(np.diff(points,axis=0),axis=1).sum())))
    return dict(schema_version="welding-generated-draft-v1",generated=True,
                source_sample_id=reference['source_sample_id'],selection_method="gpt_generated_query_draft",
                coordinate_frame="estimated_query_start_relative",unit="mm",registered_to_query=False,
                target_point_count=reference['target_point_count'],
                actual_point_count=sum(len(s['points_xyz_mm']) for s in segments),segments=segments)



def load_endpoint_condition(data_root: Path, sample_id: str) -> dict:
    import h5py
    matches=list((data_root / "1.데이터" / "Other").rglob(f"{sample_id}.h5"))
    if len(matches)!=1:
        raise ValueError(f"Cannot identify H5 for {sample_id}: {len(matches)} matches")
    with h5py.File(matches[0], "r") as handle:
        start=np.asarray(handle['trajectory'][0],dtype=float)[:3]
        end=np.asarray(handle['trajectory'][-1],dtype=float)[:3]
    if start.shape!=(3,) or end.shape!=(3,) or not np.isfinite([start,end]).all():
        raise ValueError("Invalid H5 start/end XYZ")
    return dict(known_start_xyz_mm=start.tolist(),known_end_xyz_mm=end.tolist(),
                known_end_offset_mm=(end-start).tolist(),coordinate_frame="source_robot_start_relative_mm",
                endpoint_source=str(matches[0]),gt_endpoint_used_as_input=True,
                gt_interior_path_used_as_input=False,endpoint_snapped=False)


def main() -> None:
    args = parse_args()
    config = yaml.safe_load(args.config.expanduser().read_text(encoding="utf-8"))
    if args.resume_session:
        output=args.resume_session.expanduser().resolve()
        status=json.loads((output/'status.json').read_text())
        accepted=int(status['accepted_iteration'])
        saved=json.loads((output/f'iteration_{accepted:03d}'/'plan.json').read_text())
        args.mask_session=Path(saved['previous_mask_session']) if saved.get('previous_mask_session') else None
        args.sample_id=saved['sample_id']
        session=resolve_input(args)
        instruction=saved['raw_instruction_ko']
        data_root=Path(config['data']['root']).expanduser().resolve()
        sample=load_sample(data_root,session.sample_id)
        endpoint=None if args.no_end else saved.get('endpoint_conditioning')
        if args.end and not endpoint:
            endpoint=load_endpoint_condition(data_root,session.sample_id)
        args.end=bool(endpoint)
        detections=json.loads((output/'yolo'/'detections.json').read_text())
        image_guidance=json.loads((output/'query_image_guidance_2d.json').read_text())
        query_sheet=output/'query_views.jpg'
        refined=RefinedTask.model_validate(saved['refined_task'])
        refiner_response_id=saved.get('refiner_response_id')
        retrieval=json.loads((output/'retrieval.json').read_text())
        reference_ids=saved['reference_sample_ids']
        references=prepare_reference_assets(retrieval.get('results',[]),data_root,
            list(session.polylines) if session.polylines else list(sample.images),
            output/'references',int(config['planning']['mask_line_width_px']))
        reference_trajectory_3d=json.loads((output/'reference_trajectory_3d.json').read_text())
        previous=DetailedPlan.model_validate(saved['plan'])
        if args.no_end and saved.get('gt_endpoint_used_as_input'):
            # Do not feed the old endpoint-conditioned XYZ back as a draft.
            previous=None
        feedback=args.feedback or args.instruction or input('추가 수정 지시: ').strip()
        if not feedback:
            return
        iteration=max(int(p.name.split('_')[-1]) for p in output.glob('iteration_*') if p.is_dir())+1
        api_key,key_source=load_api_key(Path(config['models']['api_keys_path']).expanduser())
        client=OpenAI(api_key=api_key)
        planner_model=str(config['models']['planner'])
        effort=str(config['models'].get('reasoning_effort','medium'))
        print(f'[RESUME] {output}; approved={accepted}; next={iteration}; END={args.end}')
    else:
        session = resolve_input(args)
        instruction = args.instruction or session.instruction
        data_root = Path(config["data"]["root"]).expanduser().resolve()
        sample = load_sample(data_root, session.sample_id)
        endpoint = load_endpoint_condition(data_root, session.sample_id) if args.end else None
        if endpoint:
            print(f"[END INPUT] source-frame mm: {endpoint['known_end_xyz_mm']}; offset={endpoint['known_end_offset_mm']}")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        output_root = Path(config["output"]["root"]).expanduser().resolve()
        output = output_root / f"{timestamp}_{session.sample_id}"
        output.mkdir(parents=True, exist_ok=False)
        (output / "endpoint_conditioning.json").write_text(json.dumps(endpoint or {"gt_endpoint_used_as_input": False}, indent=2), encoding="utf-8")
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
                endpoint,
            )
        except AuthenticationError as exc:
            raise SystemExit(
                f"OpenAI 인증 실패(401): key_source={key_source}. 유효한 프로젝트 API 키로 교체하세요."
            ) from exc
        iteration_dir = output / f"iteration_{iteration:03d}"
        iteration_dir.mkdir(parents=True)
        draft_trajectory = generated_trajectory(plan, reference_trajectory_3d)
        combined = {
            "schema_version": "welding-cot-v3",
            "endpoint_conditioning": endpoint,
            "gt_endpoint_used_as_input": bool(endpoint),
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
            "approved_instruction_en": plan.task_summary_en,
            "approved_instruction_ko": plan.task_summary_ko,
            "reference_sample_ids": reference_ids,
            "rough_trajectory_3d": draft_trajectory,
            "retrieved_reference_trajectory_3d": reference_trajectory_3d,
            "image_guidance_2d": image_guidance,
            "plan": plan.model_dump(),
            "feedback": feedback,
        }
        (iteration_dir / "plan.json").write_text(
            json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (iteration_dir / "cot_ko.md").write_text(
            render_korean_markdown(
                plan, refined, draft_trajectory, image_guidance, reference_ids
            ),
            encoding="utf-8",
        )
        (iteration_dir / "vla_prompt.md").write_text(
            render_vla_markdown(plan, refined, draft_trajectory, image_guidance),
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
            draft_trajectory, iteration_dir / "rough_trajectory_3d.jpg"
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
            command=['python',str(PROJECT_DIR.parent/'vlm_project4'/'predict.py'),
                     '--cot-session',str(output),'--mode','9-to-33','--retry-failed']
            command.append('--end' if args.end else '--no-end')
            print('[NEXT] 최종 33점 생성:')
            print(shlex.join(command))
            break
        if not answer:
            continue
        previous = plan
        feedback = answer
        iteration += 1


if __name__ == "__main__":
    main()
