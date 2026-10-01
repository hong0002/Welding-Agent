"""Tiny native-process/output fixtures. No real SDK, SSH or native code execution."""
from dataclasses import replace
import json
from pathlib import Path
import shutil
import sys
from PIL import Image, ImageDraw
import yaml

from backend.model_clients.config import ModelSettings
from backend.model_clients.native import NativeRuntime, NativeSegmentV2Client, CAMERAS, read_json
from backend.model_clients.native_rough3d import NativeRough3DV3Client
from tests.module_fakes import module_workflow
from tests.test_guided_vla import save


def candidate_workflow(root):
    root = Path(root)
    workflow, transport = module_workflow(root)
    reference = workflow.rough3d.directory
    records = root/'.cache/records'
    calls = {'segment':[], 'rough3d':[]}
    for stage in ('segment','rough3d'):
        repo = root/stage
        repo.mkdir()
        (repo/('mask.py' if stage=='segment' else 'cot.py')).write_text('# fake native source\n')
        output = root/'.cache'/stage
        config = root/(stage+'.yaml')
        payload = {'mask':{'dataset_root':str(root/'dataset/2.데이터(NIA)'), 'output_dir':str(output), 'model':'offline'},
                   'data':{'root':str(root/'dataset')},'output':{'root':str(output)},'models':{'planner':'offline'}}
        config.write_text(yaml.safe_dump(payload),encoding='utf-8')
        settings = ModelSettings(stage=stage,backend='native_v2' if stage=='segment' else 'native_3d_v3',
            repository=repo,python=Path(sys.executable),native_config=config,native_binding=root/'binding.json')
        def run(command, *, cwd, timeout, stage=stage, output=output):
            calls[stage].append(command)
            name=f'20261001_000001_{len(calls[stage]):06d}_SAMPLE_1'
            directory=output/name
            instruction=next(arg.removeprefix('--instruction=') for arg in command if arg.startswith('--instruction='))
            if stage=='segment':
                predictions={}
                for view in ('F','R','S4'):
                    path=[{'x':10.,'y':20.},{'x':90.,'y':20.}]
                    predictions[view]={'camera_id':view,'polylines':[{'points':path}],'note':''}
                save(directory/'retrieval.json',{'query_sample_id':'SAMPLE_1','results':[{'sample_id':'REF_1'}]})
                save(directory/'iteration_001/result.json',dict(sample_id='SAMPLE_1',instruction=instruction,
                    prompt_version='welding-mask-v2',predictions=predictions,retrieved_sample_ids=['REF_1']))
                for view in predictions:
                    mask=Image.new('L',(100,100));ImageDraw.Draw(mask).line([(10,20),(90,20)],fill=255,width=5)
                    for suffix in ('prediction.png','gt.png','comparison.jpg'):
                        mask.convert('RGB' if suffix.endswith('jpg') else 'L').save(directory/'iteration_001'/f'{view}_{suffix}')
                mask.convert('RGB').save(directory/'iteration_001/comparison_all.jpg')
                save(directory/'yolo/detections.json',dict(sample_id='SAMPLE_1',bbox_source='server_yolo',request_id=name,
                    manifest_path='/server/incoming/yolo_requests/'+name+'/request.json',
                    cameras={v:dict(width=100,height=100,status='detected',boxes=[]) for v in CAMERAS}))
                return 0,[str(directory/'iteration_001/comparison_all.jpg')]
            session=Path(command[-1])
            assert (session/'status.json').is_file()
            assert list(read_json(session/'iteration_001/result.json')['predictions'])==['F']
            detection=read_json(session/'yolo/detections.json')
            shutil.copytree(reference,directory)
            (directory/'query_masks.jpg').rename(directory/'query_views.jpg')
            data=read_json(directory/'iteration_001/plan.json')
            data.update(raw_instruction_ko=instruction,mask_available=True,previous_mask_session=str(session),
                yolo_request_id=detection['request_id'],planner_prompt_version='welding-detailed-plan-v3-optional-mask',
                refiner_prompt_version='welding-instruction-refiner-v2-optional-mask')
            data['image_guidance_2d']['mask_available']=True
            save(directory/'iteration_001/plan.json',data)
            save(directory/'query_image_guidance_2d.json',data['image_guidance_2d'])
            save(directory/'yolo/detections.json',detection)
            return 0,[str(directory/'iteration_001/review_all.jpg')]
        runtime=NativeRuntime(settings,records=records,run=run)
        if stage=='segment':workflow.segmentation=NativeSegmentV2Client(runtime)
        else:workflow.rough3d=NativeRough3DV3Client(runtime)
    return workflow, transport, calls
