"""Stdlib GPT completion/lineage gate, also usable before Isaac imports."""
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path

FRAME='source_robot_frame_unaligned_with_isaac'


def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_completed_gpt(attempt,manifest,job):
    attempt=Path(attempt).resolve()
    done=read(attempt/'completion.json');r=read(attempt/'response.json')
    if (done.get('response_validated') is not True or done.get('attempt_id')!=attempt.name or
            set(done['files'])!={'response.json','trajectory.npz','metadata.json'} or
            any(sha(attempt/n)!=h for n,h in done['files'].items())):raise ValueError('Incomplete GPT result')
    if (r.get('source')!='vlm_final_gpt' or r.get('provider')!='gpt' or r.get('point_count')!=33 or
        r.get('units')!='mm' or r.get('coordinate_frame')!=FRAME or
        r.get('is_robot_executable') is not False or r.get('physical_robot_executable') is not False or
        r.get('simulation_only') is not True or len(r.get('connections',[]))!=32 or
        any(v!='within_segment' for v in r['connections'])):raise ValueError('GPT output contract')
    for name in ('predicted_path_xyz_mm','ground_truth_path_xyz_mm'):
        points=r[name]
        if (not isinstance(points,list) or len(points)!=33 or any(not isinstance(p,list) or len(p)!=3 or
            any(type(v) not in (int,float) or not math.isfinite(v) for v in p) for p in points)):raise ValueError('Finite 33 XYZ required')
    for key in ('ade_mm','fde_mm'):
        if type(r[key]) not in (int,float) or not math.isfinite(r[key]) or r[key]<0:raise ValueError('Metric invalid')
    if (manifest.get('backend')!='gpt' or manifest['attempt_id']!=attempt.name or
        r['artifact_id']!=manifest['artifact_id'] or r['sample_id']!=manifest['sample_id'] or r['split']!=manifest['split'] or
        r['sample_id']!=job['scene']['sample_id'] or r['split']!=job['scene']['split'] or
        manifest['workflow_job_id']!=job['id'] or manifest['mask_views']!=['F'] or manifest['reference_in_request'] is not False or
        manifest['source_mask_id']!=job['mask']['id'] or datetime.fromisoformat(manifest['approved_at'])!=datetime.fromisoformat(job['mask']['approved_at']) or
        job['mask']['approved'] is not True or sha(manifest['source_mask'])!=manifest['source_mask_sha256']):raise ValueError('GPT lineage differs')
    if any(not (attempt/n).resolve().is_relative_to(attempt) for n in manifest['files']):raise ValueError('GPT input path')
    if any(sha(attempt/n)!=h for n,h in manifest['files'].items()):raise ValueError('GPT input changed')
    if sha(manifest['source_job'])!=manifest['source_job_sha256']:raise ValueError('GPT input job snapshot changed')
    if read(attempt/'process_exit.json').get('exit_code')!=0:raise ValueError('GPT native process failed')
    metadata=read(attempt/'metadata.json')
    if any(metadata.get(k)!=v for k,v in dict(artifact_id=r['artifact_id'],attempt_id=attempt.name,episode_id=r['sample_id'],
            split=r['split'],source='vlm_final_gpt',provider='gpt',coordinate_frame=FRAME,source_units='mm',scale_to_meters=.001,
            is_robot_executable=False,vla_orientation=False).items()):raise ValueError('GPT metadata differs')
    conditioning={k:job[k] for k in ('scene','mask','instruction','rough_mode','rough3d','rough_trajectory')}
    if job.get('native_output') is not None:conditioning['native_output']=job['native_output']
    digest=hashlib.sha256(json.dumps(conditioning,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    if digest!=manifest['workflow_conditioning_sha256']:raise ValueError('GPT current inputs changed')
    if sha(manifest['h5'])!=manifest['h5_sha256'] or sha(manifest['obj'])!=manifest['obj_sha256']:raise ValueError('Query assets changed')
    return r
