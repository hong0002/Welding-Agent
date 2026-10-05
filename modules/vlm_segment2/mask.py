#!/usr/bin/env python3
"""검색 few-shot으로 카메라별 용접 마스크를 예측하고 GT와 비교한다."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

import yaml
from openai import AuthenticationError, OpenAI
from PIL import Image
from pydantic import BaseModel, Field

from mask_data import (
    CAMERAS,
    comparison_image,
    image_data_url,
    load_sample,
    mask_metrics,
    overlay_mask,
    rasterize,
    save_contact_sheet,
)
from retrieval_client import RetrievalConfig, retrieve_sample


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = PROJECT_DIR / "config" / "config.yaml"
PROMPT_VERSION = "welding-mask-v2"


DEVELOPER_PROMPT = """# Identity

You are a visual welding-task localization specialist. Your job is to identify the
visible weld joint requested by the user and represent it as one or more ordered
center polylines in the query image.

# Input contract

- The user instruction can be written in Korean. Interpret Korean directly and
  preserve its welding-task meaning. Do not weaken, broaden, or replace it with a
  different task.
- Korean demonstratives such as "이", "해당", and "표시된" refer to the joint or
  work target indicated by the query context. When the instruction is singular,
  return only the single requested joint unless the visible geometry clearly makes
  that joint discontinuous.
- Reference examples contain an original image followed by its correct translucent
  green weld-centerline annotation. They teach appearance and annotation style only.
  Never copy their coordinates, object pose, or path shape into the query result.
- The query image is the only image whose coordinates you must return. Treat each
  camera independently and do not invent a seam that is hidden in that view.

# Localization rules

1. Follow the explicit user instruction when choosing among visible candidate joints.
2. Locate the actual interface where the requested workpieces meet. Trace the center
   of the weldable joint, not the outer silhouette of the assembled object.
3. Include enough ordered points to preserve straight segments, arcs, bends, and
   corners. Keep points in physical traversal order along each connected joint.
4. Use a separate polyline for every disconnected visible portion that is required by
   the instruction. Do not connect portions across an occlusion or empty background.
5. Exclude the worktable, fixtures, robot, torch, shadows, reflections, tack spots,
   texture boundaries, and unrelated object edges.
6. If the requested joint is absent, fully occluded, or cannot be localized reliably
   in the query view, return an empty `polylines` list. Do not guess.

# Coordinate rules

- Coordinates are pixels in the query image's original resolution.
- The origin is the top-left corner; x increases to the right and y increases down.
- Every point must satisfy 0 <= x < image_width and 0 <= y < image_height.
- A polyline must contain at least two non-duplicate points.
- Return centerlines rather than closed region polygons or bounding boxes.

# Output rules

- Follow the supplied structured-output schema exactly.
- Set `camera_id` to the query camera ID.
- Keep `note` concise and describe only visibility or ambiguity. Do not provide
  chain-of-thought or a step-by-step rationale.
"""


class Point(BaseModel):
    x: float
    y: float


class Polyline(BaseModel):
    points: list[Point] = Field(default_factory=list)


class CameraMaskPrediction(BaseModel):
    camera_id: str
    polylines: list[Polyline] = Field(default_factory=list)
    note: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="용접 작업 마스크 GPT 시연")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--sample-id")
    parser.add_argument("--instruction")
    parser.add_argument("--views", nargs="+", choices=CAMERAS)
    parser.add_argument("--top-k", type=int)
    parser.add_argument("--once", action="store_true", help="피드백 입력 없이 한 번만 실행")
    return parser.parse_args()


def load_config(path: Path) -> dict:
    if not path.is_file():
        raise SystemExit(f"설정 파일이 없습니다: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


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


def load_api_key() -> tuple[str, str]:
    environment_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if environment_key:
        return environment_key, "OPENAI_API_KEY"
    keys_path = PROJECT_DIR / "api" / "keys.json"
    if keys_path.is_file():
        payload = json.loads(keys_path.read_text(encoding="utf-8"))
        key = find_api_key(payload)
        if key:
            return key, str(keys_path)
    raise SystemExit("OPENAI_API_KEY 환경변수 또는 api/keys.json의 API 키가 필요합니다")


def prediction_paths(prediction: CameraMaskPrediction) -> list[list[list[float]]]:
    return [
        [[float(point.x), float(point.y)] for point in polyline.points]
        for polyline in prediction.polylines
        if len(polyline.points) >= 2
    ]


def prepare_examples(
    retrieval: dict,
    dataset_root: Path,
    camera: str,
    output_dir: Path,
    line_width: int,
) -> list[tuple[str, Path, Path]]:
    examples: list[tuple[str, Path, Path]] = []
    for rank, item in enumerate(retrieval.get("results", []), 1):
        sample_id = item["sample_id"]
        try:
            sample = load_sample(dataset_root, sample_id)
        except (FileNotFoundError, RuntimeError):
            continue
        paths = sample.polylines.get(camera)
        image_path = sample.images.get(camera)
        if not paths or not image_path:
            continue
        with Image.open(image_path) as source:
            image = source.convert("RGB")
        mask = rasterize(image.size, paths, line_width)
        overlay = overlay_mask(image, mask, (0, 255, 0), 125)
        overlay_path = output_dir / f"{rank:02d}_{sample_id}_{camera}_mask.jpg"
        overlay_path.parent.mkdir(parents=True, exist_ok=True)
        overlay.save(overlay_path, quality=92)
        examples.append((sample_id, image_path, overlay_path))
    return examples


def predict_camera(
    client: OpenAI,
    model: str,
    reasoning_effort: str,
    sample_id: str,
    instruction: str,
    camera: str,
    query_image: Path,
    examples: list[tuple[str, Path, Path]],
    previous: CameraMaskPrediction | None,
    feedback: str | None,
) -> tuple[CameraMaskPrediction, str]:
    with Image.open(query_image) as source:
        width, height = source.size
    content: list[dict] = []
    for index, (example_id, original, overlay) in enumerate(examples, 1):
        content.extend(
            [
                {
                    "type": "input_text",
                    "text": (
                        f'<reference_example index="{index}" sample_id="{example_id}" '
                        f'camera_id="{camera}">\n<original_image>'
                    ),
                },
                {"type": "input_image", "image_url": image_data_url(original), "detail": "high"},
                {
                    "type": "input_text",
                    "text": (
                        "</original_image>\n<correct_annotation>"
                        "The translucent green line is the correct weld-joint centerline."
                    ),
                },
                {"type": "input_image", "image_url": image_data_url(overlay), "detail": "high"},
                {"type": "input_text", "text": "</correct_annotation>\n</reference_example>"},
            ]
        )
    query_text = (
        "<query>\n"
        f"<sample_id>{escape(sample_id)}</sample_id>\n"
        f"<camera_id>{escape(camera)}</camera_id>\n"
        f'<image_size width="{width}" height="{height}" />\n'
        f'<user_instruction language="ko">{escape(instruction)}</user_instruction>\n'
        "<task>Return only the visible weld-joint centerline requested by the user "
        "in the following query image.</task>"
    )
    if previous is not None and feedback:
        query_text += (
            "\n<revision>\n<previous_prediction>"
            + previous.model_dump_json()
            + "</previous_prediction>\n"
            + '<user_feedback language="ko">'
            + escape(feedback)
            + "</user_feedback>\n"
            + "<instruction>Revise the coordinates to address this feedback while "
            + "continuing to follow the original user instruction.</instruction>\n</revision>"
        )
    query_text += "\n<query_image>"
    content.extend(
        [
            {"type": "input_text", "text": query_text},
            {"type": "input_image", "image_url": image_data_url(query_image), "detail": "high"},
            {"type": "input_text", "text": "</query_image>\n</query>"},
        ]
    )
    response = client.responses.parse(
        model=model,
        reasoning={"effort": reasoning_effort},
        input=[
            {
                "role": "developer",
                "content": [{"type": "input_text", "text": DEVELOPER_PROMPT}],
            },
            {"role": "user", "content": content},
        ],
        text_format=CameraMaskPrediction,
    )
    prediction = response.output_parsed
    if prediction is None:
        raise RuntimeError(f"GPT가 구조화된 마스크를 반환하지 않았습니다: {response.output_text}")
    if prediction.camera_id != camera:
        prediction.camera_id = camera
    return prediction, response.id


def main() -> None:
    args = parse_args()
    config = load_config(args.config.expanduser().resolve())
    mask_config = config.get("mask", {})
    retrieval_config = config.get("retrieval", {})
    sample_id = args.sample_id or input("Sample ID: ").strip()
    instruction = args.instruction or input("작업 지시: ").strip()
    if not sample_id or not instruction:
        raise SystemExit("sample_id와 작업 지시가 필요합니다")

    dataset_root = Path(mask_config["dataset_root"]).expanduser().resolve()
    query = load_sample(dataset_root, sample_id)
    views = args.views or [camera for camera in CAMERAS if camera in query.polylines]
    views = [camera for camera in views if camera in query.images]
    if not views:
        raise SystemExit("예측·비교할 카메라가 없습니다")

    top_k = args.top_k or int(retrieval_config.get("top_k", 3))
    yolo_config = config.get("yolo", {})
    server = RetrievalConfig(
        ssh_alias=config["server"]["ssh_alias"],
        remote_root=config["server"]["remote_root"],
        remote_python=retrieval_config["remote_python"],
        top_k=top_k,
        bbox_source=retrieval_config.get("bbox_source", "server_yolo"),
        yolo_python=yolo_config.get("remote_python", "/path/to/yolo-python"),
        yolo_weights=yolo_config.get("weights", "service/weights/work_target_v2-2/best.pt"),
        confidence=float(yolo_config.get("confidence", .25)),
        margin=float(yolo_config.get("margin", .10)),
        yolo_device=str(yolo_config.get("device", "0")),
    )
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output_root = Path(mask_config.get("output_dir", PROJECT_DIR / "outputs/mask_sessions"))
    session_dir = output_root.expanduser().resolve() / f"{timestamp}_{sample_id}"
    session_dir.mkdir(parents=True, exist_ok=False)
    print(f"[RETRIEVE] sample={sample_id}, top_k={top_k}")
    retrieval = retrieve_sample(server, sample_id, images=query.images, output_dir=session_dir)
    retrieved_ids = [item["sample_id"] for item in retrieval.get("results", [])]
    print(f"[RETRIEVED] {', '.join(retrieved_ids)}")
    print(
        "[RETRIEVAL_GUARD] "
        f"index_split={retrieval.get('index_split', 'unknown')}, "
        f"self_sample_excluded={retrieval.get('self_sample_excluded', False)}"
    )

    (session_dir / "retrieval.json").write_text(
        json.dumps(retrieval, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    line_width = int(mask_config.get("line_width_px", 24))
    model = str(mask_config.get("model", "gpt-6-sol"))
    reasoning_effort = str(mask_config.get("reasoning_effort", "medium"))
    example_cache = {
        camera: prepare_examples(
            retrieval, dataset_root, camera, session_dir / "fewshots" / camera, line_width
        )
        for camera in views
    }
    api_key, api_key_source = load_api_key()
    print(f"[OPENAI] model={model}, key_source={api_key_source}, prompt={PROMPT_VERSION}")
    client = OpenAI(api_key=api_key)
    previous: dict[str, CameraMaskPrediction] = {}
    feedback: str | None = None
    iteration = 1

    while True:
        iteration_dir = session_dir / f"iteration_{iteration:03d}"
        iteration_dir.mkdir(parents=True)
        predictions: dict[str, CameraMaskPrediction] = {}
        response_ids: dict[str, str] = {}
        comparison_paths: list[Path] = []
        metrics: dict[str, dict[str, float]] = {}
        for camera in views:
            print(f"[GPT] iteration={iteration} camera={camera} examples={len(example_cache[camera])}")
            try:
                prediction, response_id = predict_camera(
                    client,
                    model,
                    reasoning_effort,
                    sample_id,
                    instruction,
                    camera,
                    query.images[camera],
                    example_cache[camera],
                    previous.get(camera),
                    feedback,
                )
            except AuthenticationError as exc:
                raise SystemExit(
                    "OpenAI 인증 실패(401): 사용 중인 키 설정은 "
                    f"{api_key_source} 입니다. 이 위치의 키를 OpenAI Platform에서 발급한 "
                    "유효한 프로젝트 API 키로 바꾸세요. 환경변수를 사용하지 않으려면 "
                    "`unset OPENAI_API_KEY` 후 다시 실행하세요. 키 값은 출력하지 않았습니다."
                ) from exc
            predictions[camera] = prediction
            response_ids[camera] = response_id
            with Image.open(query.images[camera]) as source:
                image = source.convert("RGB")
            gt_mask = rasterize(image.size, query.polylines.get(camera, []), line_width)
            predicted_mask = rasterize(image.size, prediction_paths(prediction), line_width)
            iou, dice = mask_metrics(gt_mask, predicted_mask)
            metrics[camera] = {"iou": iou, "dice": dice}
            gt_mask.save(iteration_dir / f"{camera}_gt.png")
            predicted_mask.save(iteration_dir / f"{camera}_prediction.png")
            comparison = comparison_image(image, gt_mask, predicted_mask, camera, iou, dice)
            comparison_path = iteration_dir / f"{camera}_comparison.jpg"
            comparison.save(comparison_path, quality=94)
            comparison_paths.append(comparison_path)

        result = {
            "sample_id": sample_id,
            "instruction": instruction,
            "prompt_version": PROMPT_VERSION,
            "iteration": iteration,
            "feedback": feedback,
            "retrieved_sample_ids": retrieved_ids,
            "response_ids": response_ids,
            "metrics": metrics,
            "predictions": {
                camera: prediction.model_dump() for camera, prediction in predictions.items()
            },
        }
        (iteration_dir / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        contact_sheet = iteration_dir / "comparison_all.jpg"
        save_contact_sheet(comparison_paths, contact_sheet)
        mean_iou = sum(item["iou"] for item in metrics.values()) / len(metrics)
        mean_dice = sum(item["dice"] for item in metrics.values()) / len(metrics)
        print(f"[RESULT] mean IoU={mean_iou:.4f}, mean Dice={mean_dice:.4f}")
        print(f"[VIEW] {contact_sheet}")
        if args.once:
            break
        answer = input("결과가 맞으면 ok, 수정할 내용이 있으면 피드백 입력: ").strip()
        if answer.lower() == "ok":
            (session_dir / "status.json").write_text(
                json.dumps({"status": "ok", "accepted_iteration": iteration}, indent=2),
                encoding="utf-8",
            )
            print("[OK] 마스크 예측을 확정했습니다")
            break
        if not answer:
            print("피드백이 비어 있어 현재 결과를 유지합니다")
            continue
        previous = predictions
        feedback = answer
        iteration += 1


if __name__ == "__main__":
    main()
