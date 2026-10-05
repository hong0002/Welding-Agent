"""Explicit native geometry / SDK response fixtures, never network inference."""
import json
from pathlib import Path

from agents import Model
from openai.types.responses import (Response, ResponseCompletedEvent, ResponseFunctionToolCall,
                                   ResponseOutputMessage, ResponseOutputText)
from PIL import Image, ImageDraw

from backend.model_clients.native import read_json
from tests.test_guided_vla import save


def two_region_segment(directory):
    data = read_json(directory / 'iteration_001/result.json')
    for view, prediction in data['predictions'].items():
        paths = [[(10, 20), (40, 20)], [(60, 20), (90, 20)]]
        prediction['polylines'] = [dict(points=[dict(x=x, y=y) for x, y in p]) for p in paths]
        mask = Image.new('L', (100, 100))
        for p in paths:
            ImageDraw.Draw(mask).line(p, fill=255, width=5)
        mask.save(directory / 'iteration_001' / f'{view}_prediction.png')
    save(directory / 'iteration_001/result.json', data)


def matching_multi_rough(directory):
    data = read_json(directory / 'iteration_001/plan.json')
    accepted = read_json(Path(data['previous_mask_session']) / 'iteration_001/result.json')
    polylines = accepted['predictions']['F']['polylines']
    guidance = data['image_guidance_2d']
    guidance['segments'] = []
    decisions = []
    for i, polyline in enumerate(polylines):
        # The fake native model supplies points from its accepted input. The
        # integration does not generate or bridge any trajectory geometry.
        points = [[float(p['x']), float(p['y'])] for p in polyline['points']]
        sid = f'weld_{i}'
        guidance['segments'].append(dict(segment_id=sid, source_mask_id=f'F:polyline_{i}',
            connected_to_next=False, points_pixel=points,
            points_normalized=[[x/100, y/100] for x, y in points]))
        decisions.append(dict(segment_id=sid, source_mask_id=f'F:polyline_{i}',
                              direction='forward', weld_enabled=True))
    guidance['actual_point_count'] = sum(len(s['points_pixel']) for s in guidance['segments'])
    data['plan']['segment_decisions'] = decisions
    data['plan']['grounded_mask_ids'] = [f'F:polyline_{i}' for i in range(len(polylines))]
    save(directory / 'iteration_001/plan.json', data)
    save(directory / 'query_image_guidance_2d.json', guidance)


class ScriptedSemanticModel(Model):
    """Preselected semantic function calls test actual SDK dispatch, not NLP quality."""
    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = 0

    async def get_response(self, *args, **kwargs):
        raise AssertionError('Streaming SDK only')

    async def stream_response(self, system_instructions, input, model_settings, tools,
                              output_schema, handoffs, tracing, **kwargs):
        assert model_settings.parallel_tool_calls is False
        assert 'choose_welding_action' in {t.name for t in tools}
        assert 'run_guided_vla' not in {t.name for t in tools}
        outputs=[item for item in input if isinstance(item,dict) and item.get('type')=='function_call_output']
        if outputs and '"ok": false' in outputs[-1].get('output',''):
            self.steps.clear()  # Tool errors are authoritative, no scripted retries.
        self.calls += 1
        if self.steps:
            name, arguments = self.steps.pop(0)
            output = [ResponseFunctionToolCall(type='function_call', name=name,
                arguments=json.dumps(arguments), call_id=f'offline-{self.calls}')]
        else:
            output = [ResponseOutputMessage(id='offline-message', type='message', status='completed', role='assistant',
                content=[ResponseOutputText(type='output_text', text='현재 도구 결과를 확인해주세요.', annotations=[])])]
        response = Response(id=f'offline-{self.calls}', created_at=0, model='offline', object='response',
            output=output, parallel_tool_calls=False, temperature=None, tool_choice='auto', tools=[], top_p=None, status='completed')
        yield ResponseCompletedEvent(type='response.completed', response=response, sequence_number=0)
