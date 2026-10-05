#!/usr/bin/env python3
"""GPU work-target detection for uploaded queries; never reads bbox labels."""
from __future__ import annotations
import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAMERAS = ('B', 'F', 'L', 'R', 'S1', 'S2', 'S3', 'S4', 'T')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', required=True, type=Path)
    parser.add_argument('--weights', required=True, type=Path)
    parser.add_argument('--confidence', type=float, default=.25)
    parser.add_argument('--margin', type=float, default=.1)
    parser.add_argument('--device', default='0')
    args = parser.parse_args()
    if not (0 < args.confidence <= 1) or not (0 <= args.margin <= 1):
        raise ValueError('confidence must be in (0,1], margin in [0,1]')
    request = args.request.resolve()
    request.relative_to((ROOT / 'incoming/yolo_requests').resolve())
    weights = args.weights.resolve()
    weights.relative_to(ROOT.resolve())
    if not weights.is_file():
        raise FileNotFoundError(f'weights missing: {weights}')
    payload = json.loads(request.read_text())
    images = payload['images']
    if not images or any(camera not in CAMERAS for camera in images):
        raise ValueError('invalid camera manifest')
    paths = {}
    for camera in CAMERAS:
        if camera in images:
            path = (request.parent / images[camera]).resolve()
            path.relative_to(request.parent)
            if not path.is_file():
                raise FileNotFoundError(path)
            paths[camera] = path
    # Keep Ultralytics settings and auto-created artifacts under the allowed root.
    import os
    os.environ['YOLO_CONFIG_DIR'] = str(ROOT / 'service/yolo_settings')
    os.environ['MPLCONFIGDIR'] = str(ROOT / 'service/yolo_settings/matplotlib')
    import ultralytics
    from ultralytics import YOLO
    from PIL import Image
    model = YOLO(str(weights))
    results = model.predict(source=[str(p) for p in paths.values()], device=args.device,
                            conf=args.confidence, classes=[0], verbose=False, save=False)
    if len(results) != len(paths):
        raise RuntimeError('YOLO result count does not match uploaded views')
    cameras = {}
    for (camera, path), result in zip(paths.items(), results):
        with Image.open(path) as source:
            image = source.convert('RGB')
        w, h = image.size
        boxes = []
        for row in result.boxes.data.cpu().tolist():
            x1, y1, x2, y2, confidence, class_id = row
            if not all(math.isfinite(x) for x in row):
                continue
            xyxy = [max(0., min(w, x1)), max(0., min(h, y1)),
                    max(0., min(w, x2)), max(0., min(h, y2))]
            if xyxy[2] > xyxy[0] and xyxy[3] > xyxy[1]:
                boxes.append({'xyxy': xyxy, 'confidence': confidence, 'class_id': int(class_id)})
        entry = {'status': 'detected' if boxes else 'no_detection', 'width': w, 'height': h,
                 'boxes': boxes, 'full_image_path': str(path), 'crop_xyxy': None,
                 'target_image_path': None}
        if boxes:
            # Workpieces can be separate detections: retain their union, not just one part.
            x1 = min(b['xyxy'][0] for b in boxes); y1 = min(b['xyxy'][1] for b in boxes)
            x2 = max(b['xyxy'][2] for b in boxes); y2 = max(b['xyxy'][3] for b in boxes)
            dx, dy = (x2-x1)*args.margin, (y2-y1)*args.margin
            crop = [max(0, math.floor(x1-dx)), max(0, math.floor(y1-dy)),
                    min(w, math.ceil(x2+dx)), min(h, math.ceil(y2+dy))]
            target = request.parent / f'{camera}_target.png'
            image.crop(crop).save(target)
            entry.update(crop_xyxy=crop, target_image_path=str(target))
        cameras[camera] = entry
    output = request.parent / 'detections.json'
    response = {'schema_version': 1, 'bbox_source': 'server_yolo', 'sample_id': payload['sample_id'],
                'request_id': payload['request_id'], 'weights': str(weights),
                'ultralytics_version': ultralytics.__version__, 'confidence': args.confidence,
                'margin': args.margin, 'bbox_policy': 'union_of_class_0_detections',
                'coordinate_frame': 'original_image_pixels_xyxy', 'cameras': cameras,
                'manifest_path': str(output)}
    output.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(response, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        sys.exit(1)
