"""Owned F-only conditioning bridge to Segment2's existing inference function.

Imports the sibling read-only. No native main(), YOLO, retrieval or other views.
Only the two image pixels and refinement instruction enter the Responses request.
No SDK output_text, note, reasoning or exception payload is stored or printed.
"""
import importlib.util
import json
import logging
import math
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from xml.sax.saxutils import escape

from PIL import Image

VERSION = 'segment2-current-mask-refine-v1'
POLICY = """\n# Current-mask refinement
This is refinement, not fresh detection. The second image is the CURRENT edited
binary mask (white=selected, black=excluded), a human constraint. Preserve the
user's removals; never restore excluded portions. Refine only the selected joint
according to the refinement instruction. Keep disconnected portions separate.
Do not drop a selected region: if the refinement cannot be completed, return an
empty polylines list. Do not invent missing geometry. Output camera_id=F and
original-image pixel polylines using the supplied native schema. No rationale.
"""


def write(path, data):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, allow_nan=False, indent=2)


def root_api_key(root):
    from dotenv import dotenv_values
    return (dotenv_values(root/'.env',encoding='utf-8-sig',interpolate=False).get('OPENAI_API_KEY') or '').strip()


def geometry(prediction):
    # Retain structured geometry only, even when it is invalid. No free-form note.
    if prediction is None or not hasattr(prediction, 'model_dump'):
        return None
    value = prediction.model_dump(include={'camera_id', 'polylines'})
    def finite(item):
        if isinstance(item, float) and not math.isfinite(item):return None
        if isinstance(item, dict):return {k:finite(v) for k,v in item.items()}
        if isinstance(item, list):return [finite(v) for v in item]
        return item
    return finite(value)


def paths(value, size):
    if not value or value.get('camera_id') != 'F':raise ValueError('camera')
    lines = value['polylines']
    if not isinstance(lines, list) or len(lines)>4096:raise ValueError('lines')
    result=[];count=0
    for line in lines:
        points=line['points'];count+=len(points)
        if not 2<=len(points)<=4096 or count>36864:raise ValueError('points')
        vertices=[]
        for p in points:
            x,y=p['x'],p['y']
            if any(type(v) not in (int,float) or not math.isfinite(v) for v in (x,y)):
                raise ValueError('finite')
            if not (0<=x<size[0] and 0<=y<size[1]):raise ValueError('bounds')
            vertices.append([x,y])
        if any(a==b for a,b in zip(vertices,vertices[1:])):raise ValueError('duplicate')
        result.append(vertices)
    return result


def infer(native, directory, request, client):
    """Injectable offline test boundary; production calls the SAME predict_camera.

    The conditioning transport replaces the native query envelope to exclude
    sample IDs/paths/reference examples, and adds the edited mask as image #2.
    The native developer prompt, model, reasoning setting and output schema stay.
    """
    iteration=directory/'iteration_001';iteration.mkdir(exist_ok=False)
    rgb=directory/'F_rgb.png';mask=directory/'F_current_mask.png'
    with Image.open(rgb) as image:size=image.size
    captured=SimpleNamespace(value=None, status='failed')
    class ConditionedResponses:
        def parse(self, **kwargs):
            kwargs['input']=[
                {'role':'developer','content':[{'type':'input_text','text':native.DEVELOPER_PROMPT+POLICY}]},
                {'role':'user','content':[
                    {'type':'input_text','text':f'Camera F; original size {size[0]} x {size[1]}. First image: F RGB. Second image: current edited binary mask.\n<refinement_instruction>'+escape(request['instruction'])+'</refinement_instruction>'},
                    {'type':'input_image','image_url':native.image_data_url(rgb),'detail':'high'},
                    {'type':'input_image','image_url':native.image_data_url(mask),'detail':'high'}]}]
            kwargs['store']=False
            response=client.responses.parse(**kwargs)
            captured.value=geometry(response.output_parsed)
            captured.status='completed' if response.status=='completed' else 'incomplete'
            # Native predict_camera corrects camera_id. Preserve and reject a
            # mismatch instead; never silently change the model's geometry.
            if not captured.value or captured.value.get('camera_id')!='F':raise ValueError('schema')
            return response
    try:
        native.predict_camera(SimpleNamespace(responses=ConditionedResponses()),
            request['model'],request['reasoning_effort'],request['sample_id'],
            request['instruction'],'F',rgb,[],None,None)
    except Exception:
        # All native/SDK exceptions are reduced to a safe status, not their text.
        pass
    data=dict(sample_id=request['sample_id'], instruction=request['instruction'],
        prompt_version=VERSION, operation='MASK_REFINE', sdk_status=captured.status,
        predictions={'F':captured.value} if captured.value is not None else {})
    write(iteration/'result.json',data)
    try:
        vertices=paths(captured.value,size)
        raw=native.rasterize(size,vertices,request['line_width_px'])
        raw.save(iteration/'F_prediction.png')
    except (ValueError, KeyError, TypeError, OverflowError):
        pass
    print('[RESULT] MASK_REFINE raw_output_preserved',flush=True)
    return data


def main():
    root=Path(__file__).resolve().parents[2]
    repository=(root.parent/'vlm_segment2').resolve()
    directory=Path(sys.argv[1]).resolve()
    if (Path.cwd().resolve()!=repository or not directory.is_relative_to(root/'.cache')
            or directory.parent.name!='refinement'):
        raise ValueError('owned input required')
    request=json.loads((directory/'request.json').read_text(encoding='utf-8'))
    # Explicit root file only; no inherited OPENAI_API_KEY / sibling keys.json.
    key=root_api_key(root)
    if not key:
        write(directory/'worker_status.json',{'code':'MASK_REFINEMENT_NOT_CONFIGURED'})
        return 1
    # Do this before importing native/OpenAI, which reads OPENAI_LOG at import.
    for name in ('OPENAI_LOG','OPENAI_BASE_URL','OPENAI_ORG_ID','OPENAI_PROJECT_ID'):
        os.environ.pop(name,None)
    for name in ('openai','httpx','httpcore'):
        logger=logging.getLogger(name);logger.setLevel(logging.CRITICAL);logger.disabled=True
    sys.path.insert(0,str(repository))
    spec=importlib.util.spec_from_file_location('segment2_refinement_native',repository/'mask.py')
    native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)
    from openai import OpenAI
    # Fixed official API destination; ignore inherited base URLs and organization.
    with OpenAI(api_key=key,base_url='https://api.openai.com/v1',organization=None,project=None) as client:
        print('[REFINE] camera=F',flush=True)
        infer(native,directory,request,client)
    return 0


if __name__=='__main__':
    try:code=main()
    except Exception:
        print('[RESULT] MASK_REFINE worker_failed',flush=True)
        code=1
    raise SystemExit(code)
