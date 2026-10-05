"""Display native 2D guidance; never derive query 3D from masks or references."""
import numpy as np
from backend.schemas import Point2D,RoughTrajectory,TrajectorySegment
from backend.model_clients.contracts import ModelFault
from backend.model_clients.guided_vla import serialize_guidance,GuidedVLAError


def guidance_preview(result,components,instruction):
    try:
        guidance=result.image_guidance_2d
        if len(guidance['segments'])==1:serialize_guidance(result.sample_id,guidance,result.plan)
        if guidance['primary_camera']!='F' or len(guidance['segments'])!=len(instruction.region_order):
            raise ValueError('F segment/region correspondence required')
        decisions=result.plan['segment_decisions']
        if len(decisions)!=len(guidance['segments']):raise ValueError('Decision mismatch')
        segments=[];seen=set()
        for segment in guidance['segments']:
            index=int(segment['source_mask_id'].removeprefix('F:polyline_'))
            if index not in range(len(instruction.region_order)) or index in seen or segment['connected_to_next'] is not False:
                raise ValueError('Independent segment identity required')
            seen.add(index);decision=next(d for d in decisions if d['segment_id']==segment['segment_id'])
            if not decision['weld_enabled'] or decision['direction'] not in ('forward','reverse'):raise ValueError('Decision mismatch')
            points=np.asarray(segment['points_pixel'],dtype=float)
            display=points[::-1] if decision['direction']=='reverse' else points
            segments.append(TrajectorySegment(segment_id=index,region_id=instruction.region_order[index],
                points=[Point2D(x=float(x),y=float(y)) for x,y in display]))
        segments.sort(key=lambda s:s.segment_id)
        return RoughTrajectory(generator=result.native_stack+':native',artifact=result.artifact,
            segments=segments)
    except (ValueError,KeyError,TypeError,StopIteration,GuidedVLAError):
        raise ModelFault('MODEL_OUTPUT_INVALID') from None
