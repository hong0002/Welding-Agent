"""Whole-component editing of the actual 8-connected raster, never image slicing."""
import numpy as np
from PIL import Image
from backend.services.components import detect_components

class AmbiguousMaskEdit(Exception):
    question='현재 마스크에서 제외할 영역을 하나로 구분할 수 없습니다. 연결된 영역 전체를 제외할지, Canvas에서 특정 부분을 직접 지정할지 알려주세요.'

def edit_components(mask,threshold,operation,relation):
    c=detect_components(mask,threshold);regions=sorted(c.regions,key=lambda r:r.region_id)
    if len(regions)<2:raise AmbiguousMaskEdit()
    if relation in ('FIRST','SECOND'):
        target=regions[0 if relation=='FIRST' else 1]
    else:
        vertical=relation in ('TOP','BOTTOM');key=(lambda r:r.centroid.y) if vertical else (lambda r:r.centroid.x)
        ordered=sorted(regions,key=key)
        if relation=='MIDDLE':
            if len(ordered)%2==0:raise AmbiguousMaskEdit()
            target=ordered[len(ordered)//2]
        else:target=ordered[-1] if relation in ('RIGHT','BOTTOM') else ordered[0]
        # Overlapping bounds cannot establish an unambiguous spatial component.
        bounds=lambda r:(r.bounding_box.y_min,r.bounding_box.y_max) if vertical else (r.bounding_box.x_min,r.bounding_box.x_max)
        if any(bounds(a)[1]>=bounds(b)[0] for a,b in zip(ordered,ordered[1:])):raise AmbiguousMaskEdit()
    pixels=np.asarray(mask).copy()
    affected=c.labels==target.region_id if operation=='REMOVE' else (c.labels>=0)&(c.labels!=target.region_id)
    pixels[affected]=0
    return Image.fromarray(pixels),target.region_id
