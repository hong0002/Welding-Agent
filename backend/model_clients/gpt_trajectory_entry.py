"""Fixed native-function bridge. No Agent SDK, new prompt, GT target substitution or Isaac."""
import base64
import importlib.util
import io
import json
import hashlib
import os
from pathlib import Path
import sys
from datetime import datetime, timezone
from types import ModuleType


class KnownStartError(ValueError):
    code='GPT_TRAJECTORY_KNOWN_START_INVALID'


def known_start(path):
    """Read only the explicitly permitted first XYZ; never choose a substitute."""
    import h5py
    import numpy as np
    try:
        with h5py.File(path,'r') as handle:
            data=handle['trajectory']
            if data.ndim!=2 or data.shape[0]<2 or data.shape[1] not in (3,6):
                raise KnownStartError('Known start contract invalid')
            start=np.asarray(data[0,:3],dtype=float)
        if start.shape!=(3,) or not np.isfinite(start).all():raise KnownStartError('Known start invalid')
        return start
    except (OSError,ValueError,KeyError,TypeError):
        raise KnownStartError('Known start contract invalid') from None


def visualization_start(path):
    import numpy as np
    try:return known_start(path), True
    except KnownStartError:return np.zeros(3), False


def derive_rough_visualization(native,response,attempt,start_valid):
    """Native interpolation only; never absolute prediction, approval or playback."""
    try:
        plan,points=native.check_proposal(response)
        relative,_,modes=native.interpolate_corners(points,plan.connections,33)
        native.write_json(attempt/'derived_visualization.json',dict(predicted_path_xyz_mm=relative.tolist(),
            connections=modes.tolist() if hasattr(modes,'tolist') else modes,units='mm',coordinate_frame='source_robot_start_relative_mm' if start_valid else 'gpt_start_relative_visualization_mm',
            source_stage='GPT Rough',validation='DEGRADED',robot_ready=False,physical_robot_executable=False))
    except (OSError,ValueError,KeyError,TypeError):pass


def capture_stage(client,native,c,content,stage,previous,provenance,attempt):
    """Observe visible output_text before SDK schema parsing; never reasoning."""
    from backend.model_clients.geometry_display import output_geometry
    resource=client.responses;original=resource._post
    def post(*args,**kwargs):
        options=dict(kwargs.get('options') or {});parser=options.get('post_parser')
        if parser:
            def observed(response):
                # Only public assistant message text; ignore reasoning/tool items.
                for item in getattr(response,'output',[]):
                    if getattr(item,'type',None)!='message':continue
                    for block in getattr(item,'content',[]):
                        if getattr(block,'type',None)!='output_text':continue
                        points=output_geometry(getattr(block,'text',''))
                        points=[{k:p.get(k) if type(p.get(k)) in (int,float) else None for k in ('x','y','z')} if isinstance(p,dict)
                            else [v if type(v) in (int,float) else None for v in p] if isinstance(p,list) and len(p)==3 else None for p in points]
                        if points:
                            try:
                                value=json.loads(block.text);proposal=value.get('proposal',value)
                                modes=proposal.get('connections',[])
                            except (ValueError,AttributeError,TypeError):modes=[]
                            modes=[v if v in ('within_segment','between_segments','unknown') else 'unknown' for v in modes] if isinstance(modes,list) else []
                            if len(modes)!=len(points)-1 and modes!=['within_segment']:modes=['unknown']*max(0,len(points)-1)
                            native.write_json(attempt/('raw_partial_'+stage+'.json'),dict(
                                proposal=dict(points=points,connections=modes),stage=stage,units='mm',
                                coordinate_frame='gpt_start_relative_visualization_mm'))
                return parser(response)
            options['post_parser']=observed;kwargs['options']=options
        return original(*args,**kwargs)
    resource._post=post
    try:return native.call_stage(client,c,content,stage,previous,provenance)
    finally:resource._post=original


def load_native(repo, prepare=None):
    old_path=sys.path.copy();old_bytecode=sys.dont_write_bytecode
    sys.dont_write_bytecode=True
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
    if prepare is None:
        from backend.model_clients.gpt_trajectory_retrieval import prepare_examples
        prepare=prepare_examples
    # Import-only Windows fcntl compatibility; predict.main()/benchmark lock is never run.
    if os.name=='nt':
        compat=Path(__file__).resolve().parents[1]/'simulator_compat'
        sys.path.insert(0,str(compat))
    sys.path.insert(0,str(repo))
    spec=importlib.util.spec_from_file_location('welding_native_final_predictor',repo/'predict.py')
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module
    # Process-local compatibility import only. No external file is restored or
    # changed; provenance explicitly identifies the owned replacement adapter.
    names=('vlm_project2','vlm_project2.fewshot_examples')
    old={name:sys.modules.get(name) for name in names}
    package=ModuleType(names[0]);package.__path__=[]
    bridge=ModuleType(names[1]);bridge.prepare_examples=prepare
    bridge.__file__=str(Path(__file__).with_name('gpt_trajectory_retrieval.py'))
    sys.modules[names[0]]=package;sys.modules[names[1]]=bridge
    try:spec.loader.exec_module(module)
    finally:
        sys.path[:]=old_path;sys.dont_write_bytecode=old_bytecode
        for name,value in old.items():
            if value is None:sys.modules.pop(name,None)
            else:sys.modules[name]=value
    return module


def build_content(native, options, c, start, known_start_valid=True):
    import numpy as np
    from PIL import Image
    destination=Path(options['attempt'])
    label=json.loads(Path(options['label']).read_text(encoding='utf-8-sig'))
    context=dict(instruction=options['instruction'],known_start_xyz_mm=start.tolist(),
                 coordinate_frame='source_robot_start_relative_mm',camera_order=native.CAMERAS,
                 workpiece_metadata=label.get('categories',{}),
                 query_mask_source='current_web_camera_masks; not dataset GT annotation',
                 mask_conditioning_views=options.get('mask_views',['F']),mask_provenance=options.get('mask_provenance',{}))
    if not known_start_valid:
        context.update(known_start_xyz_mm=None,known_start_valid=False,
            coordinate_frame='gpt_start_relative_visualization_mm',
            coordinate_mode='relative_visualization',visualization_origin_xyz_mm=[0,0,0])
    content=[{'type':'input_text','text':json.dumps(context,ensure_ascii=False)}]
    sizes={}
    for camera in native.CAMERAS:
        with Image.open(options['images'][camera]) as src:image=src.convert('RGB')
        sizes[camera]=image.size
        if camera in context['mask_conditioning_views']:
            with Image.open(destination/f'{camera}_mask.png') as src: mask=src.copy()
            if mask.mode!='L' or mask.size!=image.size or not np.all(np.isin(np.asarray(mask),[0,255])):
                raise ValueError('Camera-specific binary mask contract')
            image=Image.composite(Image.blend(image,Image.new('RGB',image.size,(255,40,40)),.55),image,mask)
        image.thumbnail((c['image_max_side'],)*2,Image.Resampling.LANCZOS)
        buf=io.BytesIO();image.save(buf,format='JPEG',quality=90)
        content.extend([{'type':'input_text','text':f'Camera {camera}; web mask present={camera in context["mask_conditioning_views"]}; provenance={context["mask_provenance"].get(camera,[])}; original size={sizes[camera]}'},
                        {'type':'input_image','image_url':'data:image/jpeg;base64,'+base64.b64encode(buf.getvalue()).decode(),'detail':'high'}])
    native.write_json(destination/'input_manifest.json',dict(context=context,mask_views=context['mask_conditioning_views'],image_sizes=sizes,
        gt_masks_used=False,gt_endpoint_used=False,gt_interior_path_used_as_input=False,
        known_start_source='exact sample H5 trajectory[0,:3]',trajectory3_guidance_in_model_input=False,
        trajectory3_polyline_in_retrieval=any(options.get('retrieval_polylines',{}).values()),query_mask_png={v:f'{v}_mask.png' for v in context['mask_conditioning_views']}))
    return content,sizes


def main(options):
    import numpy as np
    import h5py
    import yaml
    repo=Path(options['repo']).resolve();attempt=Path(options['attempt']).resolve()
    project=Path(__file__).resolve().parents[2]
    sys.path.insert(0,str(project))
    if Path.cwd().resolve()!=repo or not attempt.is_relative_to(project/'.cache/native-models/gpt-trajectory'):
        raise ValueError('Fixed cwd/owned attempt required')
    from backend.model_clients.gpt_trajectory_retrieval import owned_preparer, verify_provenance
    native=load_native(repo,owned_preparer(options))
    config=Path(options['config']).resolve()
    c=yaml.safe_load(config.read_text(encoding='utf-8-sig'))
    c.update(end_conditioned=False,no_mask=False,no_rough=False,no_retrieval=options['retrieval_mode']=='none')
    c['data_root']=options['dataset_root']
    # User requested no automatic retry. Native model/reasoning/prompt, timeouts
    # and stages are unchanged; only this owned invocation disables SDK retry.
    c['max_retries']=0
    from dotenv import dotenv_values
    key=dotenv_values(project/'.env',encoding='utf-8-sig',interpolate=False).get('OPENAI_API_KEY')
    if not key:raise ValueError('Root key required')
    os.environ['OPENAI_API_KEY']=key
    for name in ('OPENAI_LOG','OPENAI_BASE_URL','OPENAI_ORG_ID','OPENAI_PROJECT_ID'):os.environ.pop(name,None)
    import logging
    for name in ('openai','httpx','httpcore'):logging.getLogger(name).setLevel(logging.CRITICAL)
    def event(stage,state):
        with (attempt/'stage_events.jsonl').open('a',encoding='utf-8') as file:
            file.write(json.dumps(dict(timestamp=datetime.now(timezone.utc).isoformat(),stage=stage,state=state))+'\n')
    start,start_valid=visualization_start(options['h5'])
    native.write_json(attempt/'coordinate_policy.json',dict(known_start_valid=start_valid,
        coordinate_mode='absolute' if start_valid else 'relative_visualization',
        visualization_origin_xyz_mm=None if start_valid else [0,0,0],
        display_ready=True,robot_ready=False))
    content,sizes=build_content(native,options,c,start,start_valid)
    event('retrieval','started')
    examples,provenance=native.prepare_examples(c,Path(options['dataset_root']),options['sample_id'],
                                              options['instruction'],options['retrieval_polylines'],sizes,attempt)
    verify_provenance(provenance,options['sample_id'],options['dataset_root'],provenance['mode'])
    c['no_retrieval']=provenance['mode']=='none'
    event('retrieval','completed')
    client=native.make_client(c,config.parent)
    previous=None
    for stage in ('rough','corners'):
        event(stage,'started')
        try:
            response=capture_stage(client,native,c,examples+content,stage,previous,provenance,attempt)
            native.write_json(attempt/(stage+'.json'),response)  # Persist BEFORE structural acceptance.
            plan,points=native.check_proposal(response)
        except Exception:
            if previous is not None:derive_rough_visualization(native,previous,attempt,start_valid)
            raise
        previous=response
        event(stage,'completed')
    # This is the external predictor's own fixed interpolation, not orchestration smoothing.
    relative,indices,modes=native.interpolate_corners(points,plan.connections,33)
    prediction=start+relative
    if not start_valid:
        native.write_json(attempt/'response.json',dict(artifact_id=options['artifact_id'],
            sample_id=options['sample_id'],split=options['split'],model=previous['model'],
            predicted_path_xyz_mm=relative.tolist(),connections=modes,units='mm',
            coordinate_frame='gpt_start_relative_visualization_mm',known_start_valid=False,
            coordinate_mode='relative_visualization',display_ready=True,robot_ready=False,
            physical_robot_executable=False))
        native.write_json(attempt/'worker_status.json',dict(status='visualization_only',code='OUTPUT_AVAILABLE_UNVALIDATED'))
        return  # No absolute NPZ, GT metric, completion proof or robot-ready claim.
    # Evaluation only after both GPT stages; no interior GT/endpoint enters the request.
    with h5py.File(options['h5'],'r') as handle:gt=np.asarray(handle['trajectory'][:,:3],dtype=float)
    target=np.linspace(0,len(gt)-1,33)
    gt33=np.column_stack([np.interp(target,np.arange(len(gt)),gt[:,axis]) for axis in range(3)])
    scores=native.metrics(prediction,gt33)
    response=dict(artifact_id=options['artifact_id'],sample_id=options['sample_id'],split=options['split'],
        source='vlm_final_gpt',provider='gpt',retrieval_mode=options['retrieval_mode'],model=previous['model'],point_count=33,
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
        prompt_version=native.PROMPT_VERSION,model=previous['model'],
        retrieval_mode=options['retrieval_mode'],
        retrieval_provenance_sha256=hashlib.sha256((attempt/'retrieval_provenance.json').read_bytes()).hexdigest()))
    native.write_json(attempt/'worker_status.json',{'status':'complete','xyz_source':'vlm_final_gpt.call_stage + native.interpolate_corners'})


if __name__=='__main__':
    sys.dont_write_bytecode=True
    options=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    try:main(options)
    except Exception as exc:
        # Never persist SDK exception text/payload/headers or hidden reasoning.
        path=Path(options['attempt'])/'worker_status.json'
        code=getattr(exc,'code',None)
        status=getattr(exc,'status_code',None)
        path.write_text(json.dumps({'status':'failed','exception_class':type(exc).__name__,
            'http_status':status if type(status) is int and 100<=status<=599 else None,
            'code':code if code in ('GPT_TRAJECTORY_RETRIEVAL_FAILED','GPT_TRAJECTORY_KNOWN_START_INVALID') else 'GPT_TRAJECTORY_PROCESS_FAILED'}),encoding='utf-8')
        sys.exit(1)
