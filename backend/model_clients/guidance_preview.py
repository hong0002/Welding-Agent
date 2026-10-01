"""Display native 2D guidance; never derive query 3D from masks or references."""
import numpy as np
from backend.schemas import Point2D,RoughTrajectory,TrajectorySegment
from backend.model_clients.contracts import ModelFault
from backend.model_clients.guided_vla import serialize_guidance,GuidedVLAError


def guidance_preview(result,components,instruction):
    try:
        guidance=result.image_guidance_2d
        serialize_guidance(result.sample_id,guidance,result.plan)
        if len(components.regions)!=1 or instruction.region_order!=[components.regions[0].region_id]:
            raise ValueError("Current guided contract supports one independent F segment")
        segment=guidance['segments'][0]
        points=np.asarray(segment['points_pixel'],dtype=float)
        decisions=result.plan['segment_decisions']
        if len(decisions)!=1 or not decisions[0]['weld_enabled']:raise ValueError('Decision mismatch')
        display=points[::-1] if decisions[0]['direction']=='reverse' else points
        return RoughTrajectory(generator=result.native_stack+':native',artifact=result.artifact,
            segments=[TrajectorySegment(segment_id=0,region_id=components.regions[0].region_id,
                         points=[Point2D(x=float(x),y=float(y)) for x,y in display])])
    except (ValueError,KeyError,TypeError,GuidedVLAError):
        raise ModelFault('MODEL_OUTPUT_INVALID') from None
