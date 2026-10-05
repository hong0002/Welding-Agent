from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


COLORS = ((255, 82, 82), (80, 180, 255), (255, 193, 7), (180, 90, 255))


def _draw_polyline(draw: ImageDraw.ImageDraw, points, color, width: int) -> None:
    rounded = [(round(float(x)), round(float(y))) for x, y in points]
    if len(rounded) >= 2:
        draw.line(rounded, fill=color, width=width, joint="curve")


def mask_overlay(image_path: Path, polylines, color=(0, 255, 0), width: int = 24) -> Image.Image:
    with Image.open(image_path) as source:
        image = source.convert("RGB")
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for path in polylines:
        _draw_polyline(draw, path, (*color, 150), width)
    return Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB")


def labeled_contact_sheet(items: list[tuple[str, Image.Image]], output: Path, columns: int = 2) -> Path:
    if not items:
        raise ValueError("contact sheet needs at least one image")
    thumbnails = []
    for label, image in items:
        thumb = image.copy()
        thumb.thumbnail((720, 405), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (thumb.width, thumb.height + 34), (20, 20, 20))
        canvas.paste(thumb, (0, 34))
        ImageDraw.Draw(canvas).text((10, 10), label, fill=(255, 255, 255), font=ImageFont.load_default())
        thumbnails.append(canvas)
    cell_w = max(item.width for item in thumbnails)
    cell_h = max(item.height for item in thumbnails)
    rows = math.ceil(len(thumbnails) / columns)
    sheet = Image.new("RGB", (cell_w * columns, cell_h * rows), (28, 28, 28))
    for index, item in enumerate(thumbnails):
        sheet.paste(item, ((index % columns) * cell_w, (index // columns) * cell_h))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, quality=92)
    return output


def save_query_sheet(sample, masks: dict, output: Path, width: int = 24, detections: dict | None = None) -> Path:
    items = []
    if not masks:
        for camera, path in sample.images.items():
            with Image.open(path) as source:
                image = source.convert("RGB")
            draw = ImageDraw.Draw(image)
            detection = (detections or {}).get("cameras", {}).get(camera, {})
            for box in detection.get("boxes", []):
                draw.rectangle(box["xyxy"], outline=(0, 220, 255), width=5)
            items.append((f"QUERY {camera} | YOLO workpiece box only | NO MASK", image))
        return labeled_contact_sheet(items, output, columns=3)
    for camera, paths in masks.items():
        if camera in sample.images:
            items.append((f"QUERY {camera} | approved mask red", mask_overlay(sample.images[camera], paths, (255, 45, 45), width)))
    return labeled_contact_sheet(items, output, columns=2)


def save_reference_sheet(sample, preferred_cameras: list[str], output: Path, width: int = 24) -> Path:
    cameras = [camera for camera in preferred_cameras if camera in sample.gt_polylines]
    if not cameras:
        cameras = list(sample.gt_polylines)[:4]
    items = [
        (
            f"REFERENCE {sample.sample_id} {camera} | GT mask green",
            mask_overlay(sample.images[camera], sample.gt_polylines[camera], (0, 255, 0), width),
        )
        for camera in cameras
        if camera in sample.images
    ]
    return labeled_contact_sheet(items, output, columns=2)


def _project_to_canvas(points: np.ndarray, size: tuple[int, int], padding: int = 35):
    width, height = size
    minimum = points.min(axis=0)
    maximum = points.max(axis=0)
    span = np.maximum(maximum - minimum, 1e-9)
    scale = min((width - 2 * padding) / span[0], (height - 2 * padding) / span[1])
    normalized = (points - minimum) * scale
    normalized[:, 1] = (height - 2 * padding) - normalized[:, 1]
    normalized += np.asarray([padding, padding])
    return normalized


def save_action_plot(action: dict, output: Path) -> Path:
    canvas = Image.new("RGB", (1200, 420), (245, 245, 245))
    draw = ImageDraw.Draw(canvas)
    projections = ((0, 1, "XY"), (0, 2, "XZ"), (1, 2, "YZ"))
    for panel, (axis_a, axis_b, label) in enumerate(projections):
        x0 = panel * 400
        draw.rectangle((x0, 0, x0 + 399, 419), outline=(120, 120, 120), width=1)
        draw.text((x0 + 12, 10), f"{label} start-relative mm", fill=(0, 0, 0), font=ImageFont.load_default())
        arrays=[np.asarray(segment.get("points_start_relative_mm", segment.get("points_xyz_mm")),dtype=float)
                for segment in action["segments"]]
        # A shared projection preserves spacing and relative placement between segments.
        all_projected=_project_to_canvas(np.concatenate(arrays)[:,[axis_a,axis_b]],(380,360))
        offset=0
        for segment_index, segment in enumerate(action["segments"]):
            projected=all_projected[offset:offset+len(arrays[segment_index])].copy()
            offset+=len(projected)
            projected[:, 0] += x0 + 10
            projected[:, 1] += 40
            color = (240,140,20) if segment.get("kind")=="transfer" else COLORS[segment_index % len(COLORS)]
            draw.text((x0+12, 385+segment_index*10), f"{segment['segment_id']} {segment.get('kind','reference')}", fill=color, font=ImageFont.load_default())
            _draw_polyline(draw, projected, color, 4)
            for index, (x, y) in enumerate(projected):
                radius = 5
                draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
                draw.text((x + 7, y - 7), str(index), fill=(0, 0, 0), font=ImageFont.load_default())
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)
    return output


def save_planning_review(image_guidance_path: Path, trajectory_3d_path: Path, output: Path) -> Path:
    items = []
    for label, path in (
        ("QUERY 2D IMAGE GUIDANCE", image_guidance_path),
        ("ESTIMATED 3D DRAFT | XY / XZ / YZ", trajectory_3d_path),
    ):
        with Image.open(path) as source:
            image = source.convert("RGB")
        image.thumbnail((1200, 800), Image.Resampling.LANCZOS)
        items.append((label, image))
    width = max(image.width for _, image in items)
    height = sum(image.height + 34 for _, image in items)
    sheet = Image.new("RGB", (width, height), (20, 20, 20))
    y = 0
    for label, image in items:
        ImageDraw.Draw(sheet).text((10, y + 10), label, fill=(255, 255, 255), font=ImageFont.load_default())
        y += 34
        sheet.paste(image, ((width - image.width) // 2, y))
        y += image.height
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, quality=92)
    return output


def save_plan_overlay(image_path: Path, rough_action: dict, directions: dict[str, str], output: Path) -> Path:
    with Image.open(image_path) as source:
        image = source.convert("RGB")
    draw = ImageDraw.Draw(image)
    for segment_index, segment in enumerate(rough_action["segments"]):
        points = segment["points_normalized"]
        if directions.get(segment["segment_id"]) == "reverse":
            points = list(reversed(points))
        pixels = [(x * image.width, y * image.height) for x, y in points]
        color = COLORS[segment_index % len(COLORS)]
        _draw_polyline(draw, pixels, color, 8)
        for index, (x, y) in enumerate(pixels):
            radius = 8
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color, outline=(0, 0, 0), width=2)
            draw.text((x + 10, y - 10), f"{segment['segment_id']}:{index}", fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0))
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, quality=94)
    return output
