"""Fixed native-function bridge. No Agent SDK, new prompt, GT target substitution or Isaac."""
import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import sys


def load_native(repo):
    # Import-only Windows fcntl compatibility; predict.main()/benchmark lock is never run.
    if os.name=='nt':
        compat=Path(__file__).resolve().parents[1]/'simulator_compat'
        sys.path.insert(0,str(compat))
    sys.path.insert(0,str(repo))
    spec=importlib.util.spec_from_file_location('welding_native_final_predictor',repo/'predict.py')
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    return module


def build_content(native, options, c, start):
    import numpy as np
    from PIL import Image
    destination=Path(options['attempt'])
    label=json.loads(Path(options['label']).read_text(encoding='utf-8-sig'))
    context=dict(instruction=options['instruction'],known_start_xyz_mm=start.tolist(),
                 coordinate_frame='source_robot_start_relative_mm',camera_order=native.CAMERAS,
                 workpiece_metadata=label.get('categories',{}),
                 query_mask_source='human_approved_web_F; not dataset GT annotation')
    content=[{'type':'input_text','text':json.dumps(context,ensure_ascii=False)}]
    sizes={}
    for camera in native.CAMERAS:
        with Image.open(options['images'][camera]) as src:image=src.convert('RGB')
        sizes[camera]=image.size
        if camera=='F':
            with Image.open(destination/'F_mask.png') as src: mask=src.copy()
            if mask.mode!='L' or mask.size!=image.size or not np.all(np.isin(np.asarray(mask),[0,255])):
                raise ValueError('Approved binary F contract')
            image=Image.composite(Image.blend(image,Image.new('RGB',image.size,(255,40,40)),.55),image,mask)
        image.thumbnail((c['image_max_side'],)*2,Image.Resampling.LANCZOS)
        buf=io.BytesIO();image.save(buf,format='JPEG',quality=90)
        content.extend([{'type':'input_text','text':f'Camera {camera}; approved web mask present={camera=="F"}; original size={sizes[camera]}'},
                        {'type':'input_image','image_url':'data:image/jpeg;base64,'+base64.b64encode(buf.getvalue()).decode(),'detail':'high'}])
    native.write_json(destination/'input_manifest.json',dict(context=context,mask_views=['F'],
        gt_masks_used=False,gt_endpoint_used=False,gt_interior_path_used_as_input=False,
        known_start_source='exact sample H5 trajectory[0,:3]',trajectory3_guidance_in_model_input=False,
        trajectory3_polyline_in_retrieval=True,query_mask_png='F_mask.png'))
    return content,sizes


def main(options):
    import numpy as np
    import h5py
    import yaml
    repo=Path(options['repo']).resolve();attempt=Path(options['attempt']).resolve()
    project=Path(__file__).resolve().parents[2]
    if Path.cwd().resolve()!=repo or not attempt.is_relative_to(project/'.cache/native-models/gpt-trajectory'):
        raise ValueError('Fixed cwd/owned attempt required')
    native=load_native(repo)
    config=Path(options['config']).resolve()
    c=yaml.safe_load(config.read_text(encoding='utf-8-sig'))
    c.update(end_conditioned=False,no_mask=False,no_rough=False,no_retrieval=False)
    c['data_root']=options['dataset_root']
    # Keep native key fallback, model, reasoning, timeout/retry and prompt unchanged.
    c['api_keys_path']=str((config.parent/c['api_keys_path']).resolve())
    from dotenv import dotenv_values
    key=dotenv_values(project/'.env',encoding='utf-8-sig',interpolate=False).get('OPENAI_API_KEY')
    if key and not os.getenv('OPENAI_API_KEY'):os.environ['OPENAI_API_KEY']=key
    with h5py.File(options['h5'],'r') as handle:
        start=np.asarray(handle['trajectory'][0,:3],dtype=float)
    if start.shape!=(3,) or not np.isfinite(start).all():raise ValueError('Known start invalid')
    content,sizes=build_content(native,options,c,start)
    examples,provenance=native.prepare_examples(c,Path(options['dataset_root']),options['sample_id'],
                                              options['instruction'],options['retrieval_polylines'],sizes,attempt)
    client=native.make_client(c,config.parent)
    previous=None
    for stage in ('rough','corners'):
        response=native.call_stage(client,c,examples+content,stage,previous,provenance)
        native.write_json(attempt/(stage+'.json'),response)  # Persist BEFORE structural acceptance.
        plan,points=native.check_proposal(response)
        previous=response
    # This is the external predictor's own fixed interpolation, not orchestration smoothing.
    relative,indices,modes=native.interpolate_corners(points,plan.connections,33)
    prediction=start+relative
    # Evaluation only after both GPT stages; no interior GT/endpoint enters the request.
    with h5py.File(options['h5'],'r') as handle:gt=np.asarray(handle['trajectory'][:,:3],dtype=float)
    target=np.linspace(0,len(gt)-1,33)
    gt33=np.column_stack([np.interp(target,np.arange(len(gt)),gt[:,axis]) for axis in range(3)])
    scores=native.metrics(prediction,gt33)
    response=dict(artifact_id=options['artifact_id'],sample_id=options['sample_id'],split=options['split'],
        source='vlm_final_gpt',provider='gpt',model=previous['model'],point_count=33,
        predicted_path_xyz_mm=prediction.tolist(),ground_truth_path_xyz_mm=gt33.tolist(),
        coordinate_frame='source_robot_frame_unaligned_with_isaac',units='mm',
        connections=modes,ade_mm=scores['ade_source_units'],fde_mm=scores['fde_source_units'],
        is_robot_executable=False,physical_robot_executable=False,simulation_only=True)
    native.write_json(attempt/'response.json',response)
    # Keep full precision; native simulator supports float64 arrays. Never round/source-correct.
    np.savez_compressed(attempt/'trajectory.npz',predicted_path_m=prediction*.001,ground_truth_path_m=gt33*.001)
    native.write_json(attempt/'metadata.json',dict(episode_id=options['sample_id'],split=options['split'],
        artifact_id=options['artifact_id'],attempt_id=attempt.name,source='vlm_final_gpt',provider='gpt',
        coordinate_frame=response['coordinate_frame'],source_units='mm',scale_to_meters=.001,
        start_xyz=start.tolist(),corner_indices=indices.tolist(),gt_resampling='index_linear_33',
        orientation_source='simulator_policy',vla_orientation=False,is_robot_executable=False,
        prompt_version=native.PROMPT_VERSION,model=previous['model']))
    native.write_json(attempt/'worker_status.json',{'status':'complete','xyz_source':'vlm_final_gpt.call_stage + native.interpolate_corners'})


if __name__=='__main__':
    sys.dont_write_bytecode=True
    options=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    try:main(options)
    except Exception as exc:
        # Never persist SDK exception text/payload/headers or hidden reasoning.
        path=Path(options['attempt'])/'worker_status.json'
        path.write_text(json.dumps({'status':'failed','exception_class':type(exc).__name__}),encoding='utf-8')
        sys.exit(1)
