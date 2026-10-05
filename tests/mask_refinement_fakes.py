"""Deterministic structured/native refinement outputs; no live client or imports."""
import json
from pathlib import Path
from types import SimpleNamespace
from PIL import Image,ImageDraw
from pydantic import BaseModel,Field
from backend.model_clients.native_mask_refine_entry import infer
from backend.model_clients.native import read_json


class Point(BaseModel):
    x:float
    y:float


class Polyline(BaseModel):
    points:list[Point]


class Prediction(BaseModel):
    camera_id:str='F'
    polylines:list[Polyline]=Field(default_factory=list)
    note:str='DO NOT STORE THIS NOTE'


def rasterize(size,polylines,width):
    mask=Image.new('L',size);draw=ImageDraw.Draw(mask)
    for line in polylines:
        points=[(round(x),round(y)) for x,y in line]
        draw.line(points,fill=255,width=width,joint='curve')
        radius=max(1,width//2)
        for x,y in (points[0],points[-1]):draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=255)
    return mask


def image_url(path):
    import base64
    return 'data:image/png;base64,'+base64.b64encode(Path(path).read_bytes()).decode()


class FakeNative:
    DEVELOPER_PROMPT='Native localization schema/prompt fixture'
    image_data_url=staticmethod(image_url)
    rasterize=staticmethod(rasterize)
    @staticmethod
    def predict_camera(client,model,effort,sample,instruction,camera,rgb,examples,previous,feedback):
        assert camera=='F' and examples==[] and previous is feedback is None
        response=client.responses.parse(model=model,reasoning={'effort':effort},text_format=Prediction)
        if response.output_parsed is None:raise ValueError('native malformed')
        return response.output_parsed,response.id


class RefinementProcess:
    def __init__(self, calls, *, mode='pass'):
        self.calls=calls;self.mode=mode;self.payloads=[]
    def __call__(self,command,*,cwd,timeout):
        self.calls.append(command)
        directory=Path(command[-1]);request=read_json(directory/'request.json')
        width=request['line_width_px']
        with Image.open(directory/'F_current_mask.png') as source:mask=source.copy()
        from backend.services.components import detect_components
        components=detect_components(mask,16)
        paths=[]
        for region in components.regions:
            # All native fixtures are horizontal. Match the original source line
            # after endpoint-cap inset, never run this helper in product code.
            pixels=components.labels==region.region_id
            import numpy as np
            y,x=np.where(pixels)
            radius=max(1,width//2)
            paths.append(dict(points=[dict(x=float(x.min()+radius),y=float((y.min()+y.max())/2)),
                                       dict(x=float(x.max()-radius),y=float((y.min()+y.max())/2))]))
        if self.mode=='restore':paths.insert(0,dict(points=[dict(x=10.,y=20.),dict(x=40.,y=20.)]))
        if self.mode=='missing_region':paths=paths[:1]
        if self.mode=='empty':paths=[]
        if self.mode=='malformed':prediction=None
        else:prediction=Prediction(camera_id='R' if self.mode=='foreign_camera' else 'F',polylines=paths)
        if self.mode=='process_fail':return 1,[]
        if self.mode=='timeout':
            import subprocess
            raise subprocess.TimeoutExpired(command,timeout)
        def parse(**kwargs):
            self.payloads.append(kwargs)
            if self.mode=='sdk_fail':raise RuntimeError('fake-private-secret-and-raw-payload')
            return SimpleNamespace(output_parsed=prediction,status='incomplete' if self.mode=='partial' else 'completed',id='fake')
        infer(FakeNative,directory,request,SimpleNamespace(responses=SimpleNamespace(parse=parse)))
        if self.mode=='tampered_input':(directory/'F_current_mask.png').write_bytes(b'changed')
        return 0,[]
