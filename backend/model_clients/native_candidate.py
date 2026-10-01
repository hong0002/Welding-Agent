"""Read original native 2D points independently from acceptance for Guided VLA.

No interpolation, skeleton, clipping, correction or point-order changes here.
Hard contract/integrity errors never expose a candidate for Canvas/downstream.
"""
import numpy as np
import hashlib
from pathlib import Path
from pydantic import ValidationError
from backend.schemas import (NativeTrajectoryCandidate, NativeCandidateSegment,
    NativeValidationIssue, NativeCandidateValidation)
from backend.model_clients.native import CAMERAS, read_json
from backend.model_clients.guided_vla import serialize_guidance, GuidedVLAError


MESSAGES = {
    'coordinate_contract':'필수 좌표·유한 값·point count 또는 pixel/normalized 계약이 잘못되었습니다.',
    'frame_or_dimensions':'카메라 frame 또는 원본 이미지 크기가 현재 Scene과 다릅니다.',
    'sample_or_instruction':'현재 sample 또는 지시와 다른 모델 결과입니다.',
    'source_integrity':'원본 artifact 또는 현재 승인 mask의 무결성을 확인할 수 없습니다.',
    'native_metadata':'Native JSON 복사본·승인 branch·reference 계약이 일치하지 않습니다.',
    'segment_identity':'중복 segment ID, 알 수 없는 mask ID 또는 연결된 segment 계약입니다.',
    'mask_proximity':'경로의 80% 이상이 해당 mask 영역의 2 px 이내에 있어야 하는 조건을 통과하지 못했습니다.',
    'region_mapping':'선택된 영역과 native segment의 대응을 확정할 수 없습니다.',
    'direction_consistency':'Native 진행 방향이 현재 지시의 이미지 방향과 일치하지 않습니다.',
    'guided_contract':'원본 경로가 현재 F-only Guided 입력 계약을 통과하지 못했습니다.',
    'native_incomplete':'완전한 native plan이 없습니다. 생성된 중간 artifact만 보존했습니다.',
    'native_clarification':'Native가 추가 확인을 요청해 최종 plan을 생성하지 않았습니다.',
    'auxiliary_artifacts':'필수 native 보고서 또는 시각화가 완성되지 않았습니다.',
}


def issue(code, classification='HARD_INVALID'):
    return NativeValidationIssue(code=code, classification=classification, message=MESSAGES[code])


class CandidateInvalid(Exception):
    def __init__(self, code):
        self.issue=issue(code)
        super().__init__(code)


def require(condition, code):
    if not condition:raise CandidateInvalid(code)


def read_candidate(directory, sample_id, instruction, artifact_id, scene, *, known_masks):
    """Parse native geometry; semantic/heuristic acceptance is a separate operation."""
    try:
        data=read_json(directory/'iteration_001/plan.json')
        guidance=read_json(directory/'query_image_guidance_2d.json')
        require(data['sample_id']==sample_id and data['raw_instruction_ko']==instruction,'sample_or_instruction')
        require(data['image_guidance_2d']==guidance,'native_metadata')
        require(data['plan']['status']=='ready' and data['refined_task']['status']=='ready','native_metadata')
        camera=guidance['primary_camera'];size=guidance['image_size']
        require(camera in CAMERAS and guidance['schema_version']=='welding-image-guidance-v1','frame_or_dimensions')
        view=scene.views.get(camera)
        require(view is not None and size=={'width':view.width,'height':view.height}
                and guidance['coordinate_frame_pixel']==f'image_pixel:{camera}'
                and guidance['coordinate_frame_normalized']==f'image_normalized:{camera}', 'frame_or_dimensions')
        require(data.get('mask_available',True) is True and guidance.get('mask_available',True) is True,'native_metadata')
        segments=guidance['segments'];decisions=data['plan']['segment_decisions']
        require(segments and len({s['segment_id'] for s in segments})==len(segments),'segment_identity')
        require(len({d['segment_id'] for d in decisions})==len(decisions),'segment_identity')
        require(set(data['plan']['grounded_mask_ids']) <= known_masks,'segment_identity')
        parsed=[]
        for segment in segments:
            require(isinstance(segment['segment_id'],str) and bool(segment['segment_id'])
                and segment['source_mask_id'] in known_masks and segment['source_mask_id'].startswith(camera+':')
                and segment['connected_to_next'] is False,'segment_identity')
            for points in (segment['points_pixel'],segment['points_normalized']):
                require(isinstance(points,list) and all(isinstance(p,list) and len(p)==2
                    and all(type(v) in (int,float) for v in p) for p in points),'coordinate_contract')
            decision=next((d for d in decisions if d['segment_id']==segment['segment_id']),None)
            if decision:require(decision['direction'] in ('forward','reverse') and type(decision['weld_enabled']) is bool,'segment_identity')
            item=NativeCandidateSegment(**{k:segment[k] for k in
                ('segment_id','source_mask_id','connected_to_next','points_pixel','points_normalized')},
                direction=decision['direction'] if decision else None)
            pixels=np.asarray(item.points_pixel);normalized=np.asarray(item.points_normalized)
            require(np.isfinite(pixels).all() and np.isfinite(normalized).all()
                    and len(np.unique(pixels,axis=0))>=2
                    and pixels.shape==normalized.shape and np.all(pixels>=0)
                    and np.all(pixels<[size['width'],size['height']]) and np.all(normalized>=0) and np.all(normalized<=1)
                    and np.allclose(pixels/[size['width'],size['height']],normalized,atol=1e-6,rtol=0),'coordinate_contract')
            parsed.append(item)
        require(type(guidance['actual_point_count']) is int and guidance['actual_point_count']==sum(len(s.points_pixel) for s in parsed),'coordinate_contract')
        return NativeTrajectoryCandidate(native_artifact_id=artifact_id,source_session=directory.name,
            sample_id=sample_id,primary_camera=camera,frame=guidance['coordinate_frame_pixel'],
            normalized_frame=guidance['coordinate_frame_normalized'],segments=parsed),data
    except CandidateInvalid:raise
    except (ValidationError,ValueError,KeyError,TypeError,OSError,OverflowError):
        raise CandidateInvalid('coordinate_contract') from None


def validate_candidate(candidate, data, components, instruction, report=None):
    """Soft checks keep original geometry visible but block Guided acceptance."""
    issues=[]
    try:serialize_guidance(candidate.sample_id,data['image_guidance_2d'],data['plan'])
    except GuidedVLAError:issues.append(issue('guided_contract','SOFT_WARNING'))
    if len(components.regions)!=1 or instruction.region_order!=[components.regions[0].region_id]:
        issues.append(issue('region_mapping','SOFT_WARNING'))
    for segment in candidate.segments:
        if segment.direction is None:
            issues.append(issue('region_mapping','SOFT_WARNING'))
        else:
            start,end=segment.points_pixel[0],segment.points_pixel[-1]
            if segment.direction=='reverse':start,end=end,start
            if ((instruction.direction=='left_to_right' and start[0]>=end[0])
                    or (instruction.direction=='right_to_left' and start[0]<=end[0])
                    or (instruction.direction=='top_to_bottom' and start[1]>=end[1])
                    or (instruction.direction=='bottom_to_top' and start[1]<=end[1])):
                issues.append(issue('direction_consistency','SOFT_WARNING'))
        if len(components.regions)==1 and candidate.primary_camera=='F':
            region=components.regions[0].region_id;labels=components.labels
            if labels.ndim!=2:
                issues.append(issue('frame_or_dimensions'));continue
            near=0
            for x,y in segment.points_pixel:
                x,y=round(x),round(y)
                near+=int(np.any(labels[max(0,y-2):y+3,max(0,x-2):x+3]==region))
            if near/len(segment.points_pixel)<.8:issues.append(issue('mask_proximity','SOFT_WARNING'))
    if report and not report.valid:
        for error in report.errors:
            if '80%' in error:code='mask_proximity'
            elif any(t in error for t in ('NaN/Inf','outside the image','dimensions','empty','no segments')):
                code='coordinate_contract'
            elif any(t in error for t in ('Duplicate','unknown','weld mode')):code='segment_identity'
            else:code='region_mapping'
            issues.append(issue(code,'SOFT_WARNING' if code in ('mask_proximity','region_mapping') else 'HARD_INVALID'))
    issues=list({i.code:i for i in issues}.values())
    return NativeCandidateValidation(status='FAIL' if issues else 'PASS',issues=issues)


def summary(output):
    if output is None:return None
    candidate=output.candidate
    return dict(status=output.status,native_output_generated=output.native_output_generated,
        validation_status=output.validation.status,
        warning_count=sum(i.classification=='SOFT_WARNING' for i in output.validation.issues),
        issues=[i.message for i in output.validation.issues],
        segment_count=len(candidate.segments) if candidate else 0,
        point_count=sum(len(s.points_pixel) for s in candidate.segments) if candidate else 0,
        frame=candidate.frame if candidate else None,units=candidate.units if candidate else None,
        guided_vla_allowed=output.status=='NATIVE_OUTPUT_VALIDATED' and output.validation.status=='PASS',physical_robot_executable=False)


def verify_snapshot(storage, job):
    """Recheck immutable native evidence before public display or downstream use."""
    from backend.model_clients.config import ROOT
    from backend.model_clients.native import sha256
    from backend.model_clients.native_approval import pixel_hash
    output=job.native_output
    require(output is not None and output.native_artifact_id is not None,'source_integrity')
    try:
        proof=read_json(storage.artifact_path('native_context',output.native_artifact_id,'.native-output.json'))
        directory=Path(proof['directory']).resolve()
        allowed=(ROOT/'.cache',ROOT.parent/'vlm_trajectory2/outputs',ROOT.parent/'vlm_trajectory3/outputs')
        require(any(directory.is_relative_to(p.resolve()) for p in allowed)
            and proof['job_id']==str(job.id) and proof['sample_id']==job.scene.sample_id
            and job.mask.approved and proof['mask_id']==str(job.mask.id)
            and proof['approved_at']==job.mask.approved_at.isoformat()
            and proof['mask_sha256']==sha256(storage.artifact_path('masks',job.mask.id))
            and proof['mask_pixels_sha256']==pixel_hash(storage.read_image('masks',job.mask.id))
            and proof['instruction_sha256']==hashlib.sha256(job.instruction.model_dump_json().encode()).hexdigest()
            and proof['output_sha256']==hashlib.sha256(output.model_dump_json().encode()).hexdigest(),'source_integrity')
        scene=read_json(storage.artifact_path('native_context',job.id,'.scene.json'))
        require(scene['sample_id']==job.scene.sample_id,'source_integrity')
        for view in job.scene.views:
            require(sha256(scene['images'][view])==scene['hashes'][view]
                and sha256(storage.artifact_path('scenes',job.scene.views[view].image_id))==scene['normalized_hashes'][view], 'source_integrity')
        for name,h in proof['files'].items():
            path=(directory/name).resolve()
            require(path.is_relative_to(directory) and sha256(path)==h,'source_integrity')
        if proof.get('approved_session'):
            approved=proof['approved_session'];session=Path(approved['directory']).resolve()
            require(session.is_relative_to((ROOT/'.cache').resolve())
                and sha256(session.parent/f'{session.name}.json')==approved['proof_sha256'],'source_integrity')
            for name,h in approved['files'].items():
                path=(session/name).resolve()
                require(path.is_relative_to(session) and sha256(path)==h,'source_integrity')
        return directory,proof
    except (OSError,ValueError,KeyError,AttributeError,TypeError):
        raise CandidateInvalid('source_integrity') from None
