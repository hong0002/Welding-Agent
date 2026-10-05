"""User-only endpoint identity. No dataset, GT or prediction endpoint lookup."""
import hashlib
import json
import math


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def binding(endpoint):
    return digest({k: v for k, v in endpoint.items() if k not in ('binding_hash', 'selected_at')})


def verify_endpoint(job):
    endpoint = job.get('user_endpoint')
    if endpoint is None:
        return None
    if (endpoint['job_id'] != job['id'] or endpoint['sample_id'] != job['scene']['sample_id'] or
            endpoint['sample_id'] != 'B_PR_03_0001' or endpoint['scene_id'] != job['scene']['id'] or
            endpoint['instruction_sha256'] != digest(job['instruction']) or
            endpoint['coordinate_frame'] != 'source_robot_frame_unaligned_with_isaac' or
            endpoint['units'] != 'mm' or endpoint['source'] not in ('user_selected_3d', 'dataset_gt_endpoint') or
            len(endpoint['end_xyz_mm']) != 3 or not all(math.isfinite(v) for v in endpoint['end_xyz_mm']) or
            endpoint['binding_hash'] != binding(endpoint)):
        raise ValueError('GPT2_ENDPOINT_BINDING_CHANGED')
    return endpoint
