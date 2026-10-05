from __future__ import annotations

import base64
import io
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


CAMERAS = ("B", "F", "L", "R", "S1", "S2", "S3", "S4", "T")


@dataclass(frozen=True)
class SampleData:
    sample_id: str
    split: str
    json_path: Path
    images: dict[str, Path]
    polylines: dict[str, list[list[list[float]]]]


def camera_from_filename(filename: str) -> str | None:
    for camera in CAMERAS:
        if filename.endswith(f"_{camera}_Color.png"):
            return camera
    return None


def load_sample(dataset_root: Path, sample_id: str) -> SampleData:
    matches = list(dataset_root.rglob(f"{sample_id}.json"))
    if not matches:
        raise FileNotFoundError(f"라벨 JSON을 찾을 수 없습니다: {sample_id}")
    if len(matches) > 1:
        raise RuntimeError(f"같은 sample_id JSON이 여러 개입니다: {sample_id}")
    json_path = matches[0]
    relative = json_path.relative_to(dataset_root)
    split = relative.parts[0]
    image_root = dataset_root / split / "01.원천데이터"
    sample_dirs = [path for path in image_root.rglob(sample_id) if path.is_dir()]
    if len(sample_dirs) != 1:
        raise RuntimeError(f"원천 이미지 폴더를 하나로 결정할 수 없습니다: {sample_id}")
    sample_dir = sample_dirs[0]
    payload = json.loads(json_path.read_text(encoding="utf-8"))

    images: dict[str, Path] = {}
    for item in payload.get("rgb_images", []):
        filename = item.get("filename", "")
        camera = camera_from_filename(filename)
        path = sample_dir / filename
        if camera and path.is_file():
            images[camera] = path

    polylines: dict[str, list[list[list[float]]]] = {}
    for annotation in payload.get("annotation_image", []):
        camera = camera_from_filename(annotation.get("image_filename", ""))
        if not camera:
            continue
        paths = []
        for label in annotation.get("image_label", []):
            if label.get("type") != "polyline" or label.get("label") != "full_welding":
                continue
            points = label.get("points", [])
            if len(points) >= 2:
                paths.append([[float(x), float(y)] for x, y in points])
        if paths:
            polylines[camera] = paths
    return SampleData(sample_id, split, json_path, images, polylines)


def rasterize(size: tuple[int, int], polylines: list[list[list[float]]], width: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    for path in polylines:
        points = [(round(point[0]), round(point[1])) for point in path]
        if len(points) >= 2:
            draw.line(points, fill=255, width=width, joint="curve")
            radius = max(1, width // 2)
            for x, y in (points[0], points[-1]):
                draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)
    return mask


def overlay_mask(image: Image.Image, mask: Image.Image, color: tuple[int, int, int], alpha: int) -> Image.Image:
    base = image.convert("RGBA")
    layer = Image.new("RGBA", image.size, (*color, 0))
    layer.putalpha(mask.point(lambda value: alpha if value else 0))
    return Image.alpha_composite(base, layer).convert("RGB")


def comparison_image(
    image: Image.Image,
    gt: Image.Image,
    predicted: Image.Image,
    camera: str,
    iou: float,
    dice: float,
) -> Image.Image:
    result = overlay_mask(image, gt, (0, 255, 0), 105)
    result = overlay_mask(result, predicted, (255, 0, 0), 105)
    draw = ImageDraw.Draw(result)
    text = f"{camera} | GT green | Pred red | IoU {iou:.3f} | Dice {dice:.3f}"
    draw.rectangle((0, 0, min(result.width, 850), 42), fill=(0, 0, 0))
    draw.text((12, 11), text, fill=(255, 255, 255), font=ImageFont.load_default())
    return result


def mask_metrics(gt: Image.Image, predicted: Image.Image) -> tuple[float, float]:
    gt_array = np.asarray(gt) > 0
    pred_array = np.asarray(predicted) > 0
    intersection = int(np.logical_and(gt_array, pred_array).sum())
    union = int(np.logical_or(gt_array, pred_array).sum())
    total = int(gt_array.sum() + pred_array.sum())
    iou = intersection / union if union else 1.0
    dice = (2 * intersection) / total if total else 1.0
    return iou, dice


def image_data_url(path: Path, *, max_side: int = 2048, quality: int = 90) -> str:
    with Image.open(path) as source:
        image = source.convert("RGB")
    if max(image.size) > max_side:
        scale = max_side / max(image.size)
        image = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.Resampling.LANCZOS,
        )
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def save_contact_sheet(images: list[Path], output: Path, columns: int = 2) -> None:
    if not images:
        return
    thumbs = []
    for path in images:
        with Image.open(path) as source:
            thumb = source.convert("RGB")
        thumb.thumbnail((720, 420), Image.Resampling.LANCZOS)
        thumbs.append(thumb)
    cell_w = max(image.width for image in thumbs)
    cell_h = max(image.height for image in thumbs)
    rows = (len(thumbs) + columns - 1) // columns
    sheet = Image.new("RGB", (cell_w * columns, cell_h * rows), (30, 30, 30))
    for index, thumb in enumerate(thumbs):
        x = (index % columns) * cell_w
        y = (index // columns) * cell_h
        sheet.paste(thumb, (x, y))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
