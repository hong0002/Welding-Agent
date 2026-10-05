#!/usr/bin/env python3
"""Two GPT calls → control points → fixed interpolation → simulator export/evaluation."""
from __future__ import annotations

import argparse
import shlex
import base64
import fcntl
import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Literal

import numpy as np
import yaml
from openai import OpenAI, APIError
from PIL import Image, ImageDraw
from pydantic import BaseModel
from tqdm import tqdm

from interpolate import interpolate_corners, metrics, normalize_connections, uniform_arc

ROOT=Path(__file__).resolve().parent
CAMERAS=('B','F','L','R','S1','S2','S3','S4','T')
sys.path.insert(0, str(ROOT.parent))
from vlm_project2.fewshot_examples import prepare_examples

PROMPT_VERSION='gpt-luna-path-corners-v2'
PROMPT="""Predict the main welding path from nine static RGB views, available red GT seam
masks, the task instruction and known start XYZ. Query GT trajectory is not provided.
Retrieved TRAIN examples show green seam masks, instructions and teaching action templates.
Use these to understand geometry; reference coordinates are not registered query targets.
Return a concise path description and numeric XYZ control points, not hidden chain-of-thought
or Python code. Coordinates are mm offsets from the supplied start along SOURCE ROBOT axes.
Aim to start at (0,0,0). Image directions are not robot axes; no metric calibration is supplied.
Preserve intended direction, bends, curvature and segment ordering. Multiple cameras can show
one physical seam. Missing masks are unlabeled views, not evidence of no seam.
Do not add approach, retract, finish, approval, weld ON/OFF, IK or machine settings: the output
is a geometric prediction for comparison with a VLA. Connections describe geometry only:
within_segment for continuous seam portions, between_segments for a gap between portions.
For N points return N-1 connection labels: label i describes points[i] to points[i+1].
Use unknown when a connection cannot be determined. These labels are not machine commands.
Brief uncertainty notes do not prevent returning your best path estimate. Python interpolates
between your points without correcting them using query GT. Do not fabricate calibration.
"""


def source_split(metadata):
    value = str(metadata.get('split', '')).lower()
    if value in ('train', 'training'):
        return 'train'
    if value in ('val', 'valid', 'validation'):
        return 'val'
    raise ValueError(f'Unsupported source split: {value!r}; expected train or validation')


def selected_split(sources):
    splits = {source_split(json.loads((p/'metadata.json').read_text())) for p in sources}
    return next(iter(splits)) if len(splits) == 1 else 'mixed'


def ablation(c):
    return {key: bool(c.get(key, False)) for key in ('no_mask', 'no_rough', 'no_retrieval')}


def experiment_name(c):
    return '__'.join(key.replace('_', '-') for key, value in ablation(c).items() if value) or 'full'


def prompt_for_mode(end_conditioned=False, c=None):
    prompt = PROMPT
    if end_conditioned:
        prompt = PROMPT.replace(
            'Query GT trajectory is not provided.',
            'Only the query GT endpoint is supplied as an explicit experimental input; interior GT points are not provided.'
        ) + """\nThe query context includes known_end_xyz_mm in absolute SOURCE ROBOT coordinates
and known_end_offset_mm = known_end_xyz_mm - known_start_xyz_mm. Use this endpoint in
both rough prediction and corner refinement. Start your relative path at (0,0,0) and
end it at known_end_offset_mm. Estimate the intervening geometry from the images,
masks, instruction and TRAIN examples; do not assume every path is a straight line.
Python will preserve your predicted points without snapping them to the supplied endpoint.
"""
    c = c or {}
    if c.get('no_mask'):
        prompt = prompt.replace('available red GT seam\nmasks', 'unannotated query images')
        prompt = prompt.replace('one physical seam. Missing masks are unlabeled views, not evidence of no seam.',
                                'one physical seam. No query mask or query mask coordinates are supplied.')
        prompt = prompt.replace('masks, instruction and TRAIN examples', 'instruction and available reference examples')
    if c.get('no_retrieval'):
        prompt = prompt.replace('Retrieved TRAIN examples show green seam masks, instructions and teaching action templates.\nUse these to understand geometry; reference coordinates are not registered query targets.',
                                'No retrieved examples or reference teaching actions are supplied. Use only the current query inputs.')
        prompt = prompt.replace('instruction and TRAIN examples', 'instruction').replace('instruction and available reference examples', 'instruction')
    if c.get('no_rough'):
        prompt = prompt.replace('both rough prediction and corner refinement', 'direct control-point prediction')
        prompt += '\nPredict the final control points directly. No first-stage rough path or prior response is provided.\n'
    if c.get('cot_plan'):
        prompt=prompt.replace('red GT seam', 'red approved predicted seam')
        prompt+='\nIf rough_trajectory_3d.generated is true, it is the approved estimated query draft; preserve its multi-segment topology and refine geometry, including transfer segments. Otherwise it is an unregistered reference.\n'
        prompt+='\nAny retrieved teaching template in the approved plan is NOT query-registered XYZ. Adapt it to the current query, approved instruction, known start and supplied endpoint. Preserve the requested Z-shaped ordering; do not simply copy the template. Endpoint constraints apply to the query only.\n'
    return prompt


def endpoint_context(source, start, enabled=False):
    """Expose only the last GT point in --end; ordinary mode never reads GT here."""
    if not enabled:
        return {}
    with np.load(source/'trajectory.npz',allow_pickle=False) as data:
        end=np.asarray(data['ground_truth_path_m'][-1],dtype=float)*1000
    if end.shape!=(3,) or not np.isfinite(end).all():
        raise ValueError('invalid GT endpoint')
    return {'known_end_xyz_mm':end.tolist(),
            'known_end_offset_mm':(end-start).tolist(),
            'endpoint_source':'baseline ground_truth_path_m[-1]',
            'absolute_endpoint_frame':'source_robot_frame_unaligned_with_isaac',
            'endpoint_units':'mm'}


class Point(BaseModel):
    x: float
    y: float
    z: float


class Proposal(BaseModel):
    path_description: str
    points: list[Point]
    connections: list[Literal['within_segment','between_segments','unknown']]
    uncertainties: list[str]


def read_proposal(value):
    value=dict(value)
    value.setdefault('path_description',value.get('operational_plan',''))
    if 'connections' not in value:
        value['connections']=[{'weld':'within_segment','transfer':'between_segments'}.get(v,v)
                              for v in value.get('edge_modes',[])]
    value.setdefault('uncertainties',[])
    return Proposal.model_validate(value)


def write_json(path,value):
    temp=path.with_name(path.name+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    temp.replace(path)


def key_from_file(value):
    if isinstance(value,dict):
        for key,item in value.items():
            if key.lower() in ('openai_api_key','api_key','openai') and isinstance(item,str) and item.strip(): return item.strip()
        for item in value.values():
            result=key_from_file(item)
            if result: return result


def make_client(c,config_dir):
    key=os.environ.get('OPENAI_API_KEY','').strip()
    path=(config_dir/c['api_keys_path']).resolve()
    if not key and path.is_file():
        try: key=key_from_file(json.loads(path.read_text()))
        except Exception: raise RuntimeError('Cannot read API key JSON; check api_keys_path') from None
    if not key: raise RuntimeError('Set OPENAI_API_KEY or api_keys_path')
    return OpenAI(api_key=key,timeout=c['timeout_sec'],max_retries=c['max_retries'])


def input_content(source,destination,metadata,c):
    label=json.loads((source/'source_label.json').read_text(encoding='utf-8-sig'))
    start=np.asarray(metadata['start_xyz'],dtype=float)
    if start.shape!=(3,) or not np.isfinite(start).all(): raise ValueError('invalid supplied start XYZ')
    if metadata.get('source_units')!='mm' or metadata.get('coordinate_frame')!='source_robot_frame_unaligned_with_isaac':
        raise ValueError('unsupported baseline frame/units')
    # Explicit whitelist: --end adds only the endpoint, never the interior GT path.
    context={'instruction':metadata['instruction'], 'known_start_xyz_mm':start.tolist(),
             'coordinate_frame':'source_robot_start_relative_mm', 'camera_order':CAMERAS,
             'workpiece_metadata':label.get('categories',{})}
    if c.get('cot_plan'):
        context['instruction']=c['cot_plan']['refined_task']['refined_instruction_en']
        context['approved_plan']={k:v for k,v in c['cot_plan'].items() if k not in ('refined_task','raw_instruction_ko')}
        context['instruction_priority']='Approved task summary and latest feedback override older instructions.'
    end_conditioned=bool(c.get('end_conditioned',False))
    context.update(endpoint_context(source,start,end_conditioned))
    if end_conditioned:
        print(f"[END INPUT] source-frame mm: {context['known_end_xyz_mm']}",flush=True)
    content=[{'type':'input_text','text':json.dumps(context,ensure_ascii=False)}]
    mask_paths={};rgb_paths={};available=[];polylines={};sizes={}
    for camera in CAMERAS:
        image_path=source/'raw_rgb'/f'{camera}_Color.png'
        with Image.open(image_path) as src: image=src.convert('RGB')
        polylines[camera]=[];sizes[camera]=image.size
        mask=Image.new('L',image.size,0);draw=ImageDraw.Draw(mask);found=False
        for annotation in ([] if c.get('no_mask') or c.get('cot_plan') else label.get('annotation_image',[])):
            if not annotation.get('image_filename','').endswith(f'_{camera}_Color.png'): continue
            for line in annotation.get('image_label',[]):
                if line.get('type')!='polyline' or line.get('label')!='full_welding': continue
                p=np.asarray(line.get('points',[]),dtype=float)
                if p.ndim!=2 or p.shape[1]!=2 or len(p)<2 or not np.isfinite(p).all():
                    raise ValueError(f'invalid GT mask in {camera}')
                p=np.clip(p,[0,0],np.asarray(image.size)-1)
                polylines[camera].append(p.tolist())
                draw.line([tuple(v) for v in p],fill=255,width=c['mask_width_px'],joint='curve');found=True
        if c.get('cot_plan') and not c.get('no_mask'):
            for line in c['session_polylines'].get(camera,[]):
                p=np.clip(np.asarray(line,dtype=float),[0,0],np.asarray(image.size)-1)
                polylines[camera].append(p.tolist())
                draw.line([tuple(v) for v in p],fill=255,width=c['mask_width_px'],joint='curve');found=True
        if found: available.append(camera)
        rgb_paths[camera]=str(image_path.resolve())
        if c.get('no_mask'):
            overlay=image.copy()
            image_text=f'Camera {camera}; original RGB; original size={image.size}'
        else:
            mask_path=destination/'masks'/f'{camera}.png';mask_path.parent.mkdir(exist_ok=True);mask.save(mask_path)
            mask_paths[camera]=str(mask_path.relative_to(destination))
            overlay=Image.composite(Image.blend(image,Image.new('RGB',image.size,(255,40,40)),.55),image,mask)
            image_text=f'Camera {camera}; {"approved predicted" if c.get("cot_plan") else "GT"} seam mask present={found}; original size={image.size}'
        overlay.thumbnail((c['image_max_side'],)*2,Image.Resampling.LANCZOS)
        buffer=io.BytesIO();overlay.save(buffer,format='JPEG',quality=90)
        content += [{'type':'input_text','text':image_text},
                    {'type':'input_image','image_url':'data:image/jpeg;base64,'+base64.b64encode(buffer.getvalue()).decode(),'detail':'high'}]
    if c.get('no_mask'): available=[]
    write_json(destination/'input_manifest.json',{'context':context,'raw_rgb':rgb_paths,'masks':mask_paths,
               'ablation':ablation(c), 'experiment':experiment_name(c),
               'query_mask_used_as_input':not c.get('no_mask',False),
               'available_mask_views':available, 'gt_path_used_as_input':end_conditioned,
               'gt_endpoint_used_as_input':end_conditioned, 'gt_interior_path_used_as_input':False,
               'conditioning_note':('Known start, GT endpoint and baseline instruction supplied. '
                                    if end_conditioned else 'Known start and baseline instruction supplied. ')
                                   +'Instruction may encode GT-derived direction.'})
    return content,start,available,polylines,sizes


def check_proposal(data, count=33):
    plan=read_proposal(data['proposal'])
    points=np.asarray([[p.x,p.y,p.z] for p in plan.points],dtype=float)
    # Only structural checks needed to interpolate. No subjective review or exact-9 gate.
    interpolate_corners(points,plan.connections,count)
    return plan,points


def call_stage(client,c,content,stage,previous=None,provenance=None):
    request=list(content)
    count=c["output_points"]
    if stage == 'corners' and previous is None:
        task=(f'Predict the main welding path directly from the supplied query inputs and any provided examples. '
              f'Return 2 to {count} ordered XYZ control points including every important bend and enough points for curves. '
              f'No initial rough path is provided. Python will linearly interpolate these control points to {count} points. '
              'Do not add points just to fill a quota; return geometric connections and a concise path description.')
    elif previous is None:
        task=f"Create an initial rough path with approximately {c['rough_points']} ordered points (2..{count}) and a concise path description."
    else:
        task=(f'Refine the initial approximate path below using the images and instruction. Return 2 to {count} ordered '
              'control points including every important bend. Keep useful curvature-defining points on arcs; '
              f'Python will interpolate to {count} points between adjacent control points. Do not output {count} points '
              'just to fill a quota. Return geometric connections and the updated path description.\n'+json.dumps(read_proposal(previous['proposal']).model_dump(),ensure_ascii=False))
    if previous is None and stage == 'rough' and c['rough_points'] == 4:
        task='Create an initial rough path with exactly 4 ordered XYZ points, preserving endpoints and the most important bends. Return geometric connections and a concise path description.'
    request.append({'type':'input_text','text':task})
    response=client.responses.parse(model=c['model'],reasoning={'effort':c['reasoning_effort']},
        max_output_tokens=c['max_output_tokens'],store=False,
        input=[{'role':'developer','content':prompt_for_mode(c.get('end_conditioned',False),c)},
               {'role':'user','content':request}],text_format=Proposal)
    if response.output_parsed is None: raise ValueError(f'{stage}: no structured output')
    return {'stage':stage,'prompt_version':PROMPT_VERSION,'fewshot':provenance,
            'ablation':ablation(c),'experiment':experiment_name(c),
            'end_conditioned':bool(c.get('end_conditioned',False)),
            'rough_points_requested':c['rough_points'],'output_points':count,
            'previous_response_id':previous.get('response_id') if previous else None,
            'model':response.model,'response_id':response.id,
            'usage':response.usage.model_dump() if response.usage else None,'proposal':response.output_parsed.model_dump()}


PREDICTION_SCHEMA = 'gpt2-prediction-only-v1'


def prediction_input_eligible(source):
    """Inference inputs only; no query trajectory or evaluation baseline read."""
    try:
        m=json.loads((source/'metadata.json').read_text(encoding='utf-8-sig'))
        start=np.asarray(m['start_xyz'],dtype=float)
        source_split(m)
        return (start.shape==(3,) and np.isfinite(start).all() and
                m['source_units']=='mm' and m['coordinate_frame']=='source_robot_frame_unaligned_with_isaac' and
                isinstance(m['instruction'],str) and bool(m['instruction'].strip()) and bool(m['episode_id']) and
                all((source/n).is_file() for n in ('source_label.json',*[f'raw_rgb/{v}_Color.png' for v in CAMERAS])))
    except (OSError,ValueError,KeyError,TypeError):
        return False


def export_prediction_only(destination,metadata,start,prediction,modes,corner_indices,available,stages,c):
    """Native prediction keys, no GT, baseline arrays or metrics."""
    if prediction.shape!=(c['output_points'],3) or not np.isfinite(prediction).all():
        raise ValueError('invalid final prediction')
    np.savez_compressed(destination/'trajectory.npz',predicted_path_xyz=prediction,
                        predicted_path_m=prediction*.001,start_xyz=start,
                        predicted_delta_xyz=np.diff(prediction,axis=0),corner_indices=corner_indices,connections=modes)
    for name,values in [('predicted_path_source',prediction),('predicted_path_m',prediction*.001)]:
        np.savetxt(destination/f'{name}.csv',values,delimiter=',',header='x,y,z',comments='')
    output={'episode_id':metadata['episode_id'],'split':source_split(metadata),'instruction':metadata['instruction'],
            'prediction_schema':PREDICTION_SCHEMA,'prediction_only':True,'evaluation_performed':False,
            'source_units':'mm','scale_to_meters':.001,'coordinate_frame':'source_robot_frame_unaligned_with_isaac',
            'start_xyz':start.tolist(),'known_start_application_count':1,
            'action_definition':f'{len(prediction)-1} local delta-XYZ actions',
            'output_points':len(prediction),'rough_points_requested':c['rough_points'],
            'method':'GPT rough path + GPT corners + fixed Python linear interpolation',
            'stages':stages,'export_version':PROMPT_VERSION,'mask_policy':'all_available_gt_seam_annotations',
            'available_mask_views':available,'gt_path_used_as_model_input':False,
            'gt_endpoint_used_as_model_input':False,'gt_interior_path_used_as_model_input':False,
            'model_family':'GPT6-Luna','model':c['model'],'reasoning_effort':c['reasoning_effort'],
            'conditioning':'query instruction and known start XYZ','ablation':ablation(c),'experiment':experiment_name(c),
            'query_mask_used_as_input':True,'rough_stage_used':True,'retrieval_used':True,
            'files':{'npz':f'{destination.name}/trajectory.npz'}}
    write_json(destination/'metadata.json',output)


def export(source,destination,metadata,start,points,modes,corner_indices,available,stages,end_conditioned=False,c=None):
    prediction=start+points
    if (c or {}).get('prediction_only'):
        if end_conditioned or experiment_name(c)!='full' or c.get('cot_plan'):
            raise ValueError('prediction-only requires original Full inference without GT endpoint')
        export_prediction_only(destination,metadata,start,prediction,modes,corner_indices,available,stages,c)
        return
    # Full-path evaluation happens after prediction; --end previously exposed only the last point.
    with np.load(source/'trajectory.npz',allow_pickle=False) as data:
        gt_m=np.asarray(data['ground_truth_path_m'],dtype=float)
        baseline_pred=np.asarray(data['predicted_path_m'],dtype=float)*1000
    original_gt_m=gt_m.copy()
    gt=gt_m*1000
    if len(prediction) != len(gt):
        gt=uniform_arc(gt,len(prediction))
        baseline_pred=uniform_arc(baseline_pred,len(prediction))
        gt_m=gt*.001
    scores=metrics(prediction,gt)
    baseline_scores=metrics(baseline_pred,gt)
    np.savez_compressed(destination/'trajectory.npz',predicted_path_m=prediction*.001,ground_truth_path_m=gt_m,
                        predicted_path_xyz=prediction,ground_truth_path_xyz=gt,start_xyz=start,
                        predicted_delta_xyz=np.diff(prediction,axis=0),ground_truth_delta_xyz=np.diff(gt,axis=0),
                        corner_indices=corner_indices,connections=modes,original_ground_truth_path_m=original_gt_m)
    for name,values in [('predicted_path_source',prediction),('predicted_path_m',prediction*.001),
                        ('ground_truth_path_source',gt),('ground_truth_path_m',gt_m)]:
        np.savetxt(destination/f'{name}.csv',values,delimiter=',',header='x,y,z',comments='')
    output={'episode_id':metadata['episode_id'],'export_index':metadata.get('export_index'),
            'split':source_split(metadata),'instruction':metadata['instruction'],
            'source_units':'mm','scale_to_meters':.001,'coordinate_frame':'source_robot_frame_unaligned_with_isaac',
            'start_xyz':start.tolist(),'action_definition':f'{len(prediction)-1} local delta-XYZ actions',
            'output_points':len(prediction), 'rough_points_requested':(c or {}).get('rough_points',9),
            'gt_resampling':'uniform_arc' if len(original_gt_m)!=len(prediction) else 'unchanged',
            'method':'GPT rough path + GPT corners + fixed Python linear interpolation',
            'stages':stages, 'export_version':PROMPT_VERSION,
            'mask_policy':'all_available_gt_seam_annotations','available_mask_views':available,
            'gt_path_used_as_model_input':end_conditioned,
            'gt_endpoint_used_as_model_input':end_conditioned,
            'gt_interior_path_used_as_model_input':False,
            'model_family':'GPT6-Luna-End' if end_conditioned else 'GPT6-Luna',
            'conditioning':'baseline instruction and known start XYZ'+(' + GT endpoint XYZ' if end_conditioned else ''),
            'metrics':scores,'baseline_metrics_on_same_gt':baseline_scores,
            'baseline_directory':str(source.resolve()),'files':{'npz':f'{destination.name}/trajectory.npz'}}
    if end_conditioned:
        output.update(known_end_xyz_mm=gt[-1].tolist(),known_end_offset_mm=(gt[-1]-start).tolist(),
                      endpoint_source='baseline ground_truth_path_m[-1]',endpoint_snapped=False,
                      evaluation_note='GT endpoint is an input; FDE measures endpoint adherence, not unseen endpoint prediction.')
    c=c or {}
    output.update(ablation=ablation(c),experiment=experiment_name(c),
                  mask_policy='none' if c.get('no_mask') else 'all_available_gt_seam_annotations',
                  query_mask_used_as_input=not c.get('no_mask',False),
                  rough_stage_used=not c.get('no_rough',False),
                  retrieval_used=not c.get('no_retrieval',False))
    if c.get('cot_plan'):
        output.update(mask_policy='approved_predicted_masks',cot_session=c['cot_session'],
                      instruction=c['cot_plan']['refined_task']['refined_instruction_en'],
                      rough_stage_used=False,method='Approved project2 reference plan + GPT corners + interpolation')
    if c.get('no_rough'):
        output['method']='GPT direct control points + fixed Python linear interpolation'
    write_json(destination/'metadata.json',output)  # export commit marker, written last


def summarize(output,sources,end_conditioned=False,c=None):
    records=[];failures=[]
    for source in sources:
        path=output/source.name/'metadata.json'
        if path.is_file() and (not (output/source.name/'status.json').exists() or json.loads((output/source.name/'status.json').read_text()).get('status')=='complete'):
            records.append(json.loads(path.read_text()))
        else:
            status=output/source.name/'status.json'
            failures.append({'directory':source.name,'status':json.loads(status.read_text()) if status.exists() else 'not_run'})
    summary={'selected_records':len(sources),'exported_records':len(records),'skipped':failures,
             'source_units':'mm','split':selected_split(sources),'prompt_version':PROMPT_VERSION,
             'comparison_scope':'identical completed sample subset, identical supplied start/instruction and GT arrays',
             'completed_episode_ids':[r['episode_id'] for r in records]}
    summary.update(model_family='GPT6-Luna-End' if end_conditioned else 'GPT6-Luna',
                   ablation=ablation(c or {}),experiment=experiment_name(c or {}),
                   gt_endpoint_used_as_model_input=end_conditioned,
                   gt_interior_path_used_as_model_input=False)
    if end_conditioned:
        summary['comparison_scope']+='; GPT additionally receives GT endpoint, so input conditions differ from baseline'
        summary['evaluation_note']='FDE measures adherence to a supplied endpoint. Predicted XYZ are not snapped or aligned.'
    if (c or {}).get('prediction_only'):
        summary.update(prediction_only=True,prediction_schema=PREDICTION_SCHEMA,evaluation_performed=False,
                       comparison_scope='prediction-only; no query GT or baseline evaluation')
        write_json(output/'summary.json',summary)
        return
    for key in ('ade_source_units','fde_source_units','max_error_source_units','uniform_arc_ade_mm'):
        summary['mean_'+key]=float(np.mean([r['metrics'][key] for r in records])) if records else None
        summary['baseline_mean_'+key]=float(np.mean([r['baseline_metrics_on_same_gt'][key] for r in records])) if records else None
    write_json(output/'summary.json',summary)
    if records:
        print(f"[METRICS] n={len(records)}/{len(sources)} ADE={summary['mean_ade_source_units']:.3f} mm FDE={summary['mean_fde_source_units']:.3f} mm")
        print(f"[BASELINE same samples] ADE={summary['baseline_mean_ade_source_units']:.3f} mm FDE={summary['baseline_mean_fde_source_units']:.3f} mm")


def resume_queue(selected, output, refresh=False, retry_failed=False, cached_only=False,no_rough=False):
    """Count existing work before tqdm starts; never regenerate committed exports implicitly."""
    pending=[]
    skipped={'complete':0,'failed':0,'missing_cache':0}
    for source in selected:
        destination=output/source.name
        status_path=destination/'status.json'
        state=json.loads(status_path.read_text()) if status_path.exists() else {}
        completed=state.get('status')=='complete' and all(
            (destination/name).is_file() for name in ('metadata.json','trajectory.npz'))
        required_stages=('corners',) if no_rough else ('rough','corners')
        both_cached=all((destination/f'{stage}.json').is_file() for stage in required_stages)
        if completed and not refresh:
            skipped['complete']+=1
        elif cached_only and not both_cached:
            skipped['missing_cache']+=1
        elif state.get('status')=='failed' and not (retry_failed or refresh or both_cached):
            skipped['failed']+=1
        else:
            pending.append(source)
    return pending,skipped


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',type=Path,default=ROOT/'config.yaml')
    parser.add_argument('--sample-id','--id',dest='sample_id',nargs='+',help='select one or more sample IDs')
    parser.add_argument('--limit',type=int)
    parser.add_argument('--prediction-only',action='store_true',help='Full inference inputs only; export native predictions without query GT/baseline evaluation')
    parser.add_argument('--cot-session',type=Path,help='approved project2 session; reuse predicted masks and reference plan, skip rough generation')
    parser.add_argument('--mode',choices=('9-to-33','4-to-9'),help='Point-count preset; default uses config')
    parser.add_argument('--all-ablations',action='store_true',help='run Full, no-mask, no-rough, no-retrieval, no-rough+no-retrieval, and all removed sequentially')
    parser.add_argument('--retry-failed',action='store_true')
    endpoint_flags=parser.add_mutually_exclusive_group()
    endpoint_flags.add_argument('--no-end',action='store_true',help='disable inherited endpoint input')
    endpoint_flags.add_argument('--end',action='store_true',help='supply GT endpoint to both GPT stages; export separately to GPT6-Luna-End')
    parser.add_argument('--no-mask',action='store_true',help='remove query GT masks from all GPT calls; freeze Full retrieval')
    parser.add_argument('--no-rough',action='store_true',help='skip first GPT call and directly predict final control points')
    parser.add_argument('--no-retrieval',action='store_true',help='omit search and all reference examples from every GPT call')
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument('--refresh-predictions',action='store_true',help='new retrieved examples and two new paid GPT calls')
    modes.add_argument('--cached-only',action='store_true',help='export cached responses only, without SSH/API')
    args=parser.parse_args()
    if args.prediction_only and any((args.end,args.cot_session,args.all_ablations,args.no_mask,args.no_rough,args.no_retrieval)):
        parser.error('--prediction-only requires original Full inference without GT endpoint or ablations')
    if args.all_ablations:
        # Full runs first so no-mask can reuse exactly the same retrieval examples.
        variants=((), ('--no-mask',), ('--no-rough',), ('--no-retrieval',),
                  ('--no-rough','--no-retrieval'),
                  ('--no-mask','--no-rough','--no-retrieval'))
        switches={'--all-ablations','--no-mask','--no-rough','--no-retrieval'}
        forwarded=[arg for arg in sys.argv[1:] if arg not in switches]
        for flags in variants:
            label=' + '.join(flag[2:] for flag in flags) or 'full'
            print(f'[ABLATION] {label}; endpoint={args.end}',flush=True)
            result=subprocess.run([sys.executable,str(Path(__file__).resolve()),*forwarded,*flags])
            if result.returncode:
                # In particular, do not keep making API calls after an API failure.
                return result.returncode
        return 0
    config_path=args.config.resolve();c=yaml.safe_load(config_path.read_text())
    if args.prediction_only: c['prediction_only']=True
    if args.cot_session:
        sys.path.insert(0,str(ROOT.parent/"vlm_project2"))
        from vlm_project2.data import load_accepted_session
        session=args.cot_session.resolve()
        state=json.loads((session/'status.json').read_text())
        iteration=session/f"iteration_{int(state['accepted_iteration']):03d}"
        plan=json.loads((iteration/'plan.json').read_text())
        if plan.get('gt_endpoint_used_as_input') and not args.no_end:
            args.end=True
            print('[END] inherited endpoint conditioning from project2 session',flush=True)
        masks=load_accepted_session(Path(plan['previous_mask_session']))
        if masks.sample_id!=plan['sample_id']:
            raise ValueError('mask and CoT sample IDs differ')
        plan['approved_instruction_en']=plan.get('approved_instruction_en') or plan['plan']['task_summary_en']
        # Remove stale task scope from the downstream prompt, not from original files.
        plan['refined_task']['refined_instruction_en']=plan['approved_instruction_en']
        plan['refined_task']['refined_instruction_ko']=plan['plan']['task_summary_ko']
        c['discard_endpoint_draft']=bool(args.no_end and plan.get('gt_endpoint_used_as_input'))
        if c['discard_endpoint_draft']:
            # Old XYZ and free-text constraints can reveal the previously supplied endpoint.
            plan={key:plan[key] for key in ('sample_id','previous_mask_session','approved_instruction_en','planner_response_id')}
            plan['refined_task']={'refined_instruction_en':plan['approved_instruction_en']}
            print('[NO-END] old endpoint-conditioned draft omitted; infer coordinates anew',flush=True)
        c.update(cot_plan=plan,session_polylines=masks.polylines,cot_session=str(session))
        args.sample_id=[plan['sample_id']]
    c['end_conditioned']=args.end
    c.update(no_mask=args.no_mask,no_rough=args.no_rough,no_retrieval=args.no_retrieval)
    if args.mode:
        c['rough_points'],c['output_points']=map(int,args.mode.split('-to-'))
    if not 2<=c['rough_points']<=c['output_points']:
        raise ValueError('Require 2 <= rough_points <= output_points')
    baseline=(config_path.parent/c['baseline_root']).resolve()
    regular_output=(config_path.parent/c['output_root']).resolve()
    output=((config_path.parent/c.get('end_output_root','../GPT6-Luna-End/welding_validation_gpt6_luna_end')).resolve()
            if args.end else regular_output)
    if args.end and (output==regular_output or output in regular_output.parents or regular_output in output.parents):
        raise ValueError('end_output_root must be separate from output_root')
    if args.prediction_only: output=output.with_name(output.name+'__prediction-only')
    if (c['rough_points'],c['output_points']) != (9,33):
        output=output.with_name(output.name+f"__{c['rough_points']}-to-{c['output_points']}")
    if args.cot_session:
        fingerprint=hashlib.sha256(json.dumps([c['cot_plan'],c['session_polylines']],sort_keys=True).encode()).hexdigest()[:12]
        output=output.with_name(output.name+'__cot-session-'+fingerprint)
    full_output=output
    experiment=experiment_name(c)
    if experiment!='full':
        output=output.with_name(output.name+'__'+experiment)
    if baseline==output or baseline in output.parents: raise ValueError('output must not be inside baseline export')
    sources=[p.parent for p in sorted(baseline.glob('*/metadata.json')) if (prediction_input_eligible(p.parent) if args.prediction_only else (p.parent/'trajectory.npz').is_file())]
    if not sources: raise ValueError('no baseline samples found')
    selected=sources
    if args.sample_id:
        selected=[p for p in selected if json.loads((p/'metadata.json').read_text())['episode_id'] in args.sample_id]
        found={json.loads((p/'metadata.json').read_text())['episode_id'] for p in selected}
        if set(args.sample_id)-found: raise ValueError('requested sample not found')
    if args.limit is not None:
        if args.limit<1: raise ValueError('--limit must be positive')
        selected=selected[:args.limit]
    public={k:v for k,v in c.items() if k not in ('api_keys_path','output_root')}
    build={'settings':public,'prompt':prompt_for_mode(args.end,c),'prompt_version':PROMPT_VERSION,
           'code_hash':hashlib.sha256(b''.join(p.read_bytes() for p in sorted(ROOT.glob('*.py')))).hexdigest()}
    output.mkdir(parents=True,exist_ok=True)
    with (output/'.predict.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        build_path=output/'build.json'
        if build_path.exists() and json.loads(build_path.read_text())!=build:
            old_build=json.loads(build_path.read_text())
            if bool(old_build.get('settings',{}).get('end_conditioned',False))!=args.end:
                raise RuntimeError('Output contains the other endpoint condition; choose a separate output directory')
            if ablation(old_build.get('settings',{})) != ablation(c):
                raise RuntimeError('Output contains another ablation condition')
            history=output/'build_history';history.mkdir(exist_ok=True)
            write_json(history/(hashlib.sha256(build_path.read_bytes()).hexdigest()+'.json'),old_build)
        write_json(build_path,build)
        pending,skipped=resume_queue(selected,output,args.refresh_predictions,args.retry_failed,args.cached_only,args.no_rough or bool(args.cot_session))
        print(f"[RESUME] total={len(selected)}; completed_skip={skipped['complete']}; "
              f"other_skip={skipped['failed']+skipped['missing_cache']}; remaining={len(pending)}",flush=True)
        family='GPT6-Luna-End' if args.end else 'GPT6-Luna'
        print(f"[MODE] {family}; experiment={experiment}; GT endpoint input={args.end}; output={output}",flush=True)
        client=None
        try:
            for source in tqdm(pending,total=len(selected),initial=len(selected)-len(pending),
                               desc=f'{family} {selected_split(selected)}',unit='sample'):
                destination=output/source.name;destination.mkdir(exist_ok=True)
                status_path=destination/'status.json'
                old=json.loads(status_path.read_text()) if status_path.exists() else {}
                try:
                    signature={'labels_sha256':hashlib.sha256((source/'source_label.json').read_bytes()).hexdigest(),
                               'metadata_sha256':hashlib.sha256((source/'metadata.json').read_bytes()).hexdigest(),
                               'files':{str(p.relative_to(source)):[p.stat().st_size,p.stat().st_mtime_ns]
                                        for p in [*([] if args.prediction_only else [source/'trajectory.npz']),*[source/'raw_rgb'/f'{cam}_Color.png' for cam in CAMERAS]]}}
                    signature_path=destination/'source_signature.json'
                    if signature_path.exists() and json.loads(signature_path.read_text())!=signature:
                        raise RuntimeError('baseline source changed: use a new output_root to avoid stale cached predictions')
                    write_json(signature_path,signature)
                    metadata=json.loads((source/'metadata.json').read_text())
                    source_split(metadata)
                    content,start,available,polylines,sizes=input_content(source,destination,metadata,c)
                    previous=None;examples=None;provenance=None;stages={};rough_regenerated=False
                    if args.cot_session and c.get('discard_endpoint_draft'):
                        examples=[];provenance={'applied':False,'reason':'discarded old endpoint-conditioned draft'}
                        write_json(destination/'external_plan.json',c['cot_plan'])
                    if args.cot_session and not c.get('discard_endpoint_draft'):
                        reference=c['cot_plan']['rough_trajectory_3d']
                        xyz=[point for segment in reference['segments'] for point in segment['points_xyz_mm']]
                        previous={'response_id':c['cot_plan'].get('planner_response_id'),
                                  'proposal':{'points':[dict(zip(('x','y','z'),point)) for point in xyz],
                                              'connections':[], 'path_description':'Approved estimated query draft; retain segment topology.' if reference.get('generated') else 'Unregistered retrieved teaching template; adapt to approved query plan.'}}
                        examples=[];provenance={'applied':True,'source':'project2 approved plan',
                                                'sample_ids':c['cot_plan'].get('reference_sample_ids',[])}
                        write_json(destination/'external_plan.json',c['cot_plan'])
                    if args.no_retrieval:
                        examples=[];provenance={'applied':False,'reason':'no-retrieval ablation','sample_ids':[]}
                    write_json(status_path,{'status':'processing'})
                    for stage in (('corners',) if args.no_rough or args.cot_session else ('rough','corners')):
                        path=destination/f'{stage}.json'
                        response=json.loads(path.read_text()) if path.exists() and not args.refresh_predictions else None
                        if response and bool(response.get('end_conditioned',False))!=args.end:
                            raise RuntimeError('Cached response belongs to a different endpoint condition')
                        if response and ablation(response.get('ablation',{}))!=ablation(c):
                            raise RuntimeError('Cached response belongs to a different ablation condition')
                        if stage=='corners' and response and previous is not None:
                            parent_changed=('previous_response_id' in response and response['previous_response_id']!=previous.get('response_id'))
                            legacy_after_new_rough=('previous_response_id' not in response and previous.get('prompt_version')==PROMPT_VERSION)
                            if rough_regenerated or parent_changed or legacy_after_new_rough:
                                response=None
                        if response is not None:
                            try: check_proposal(response,c['output_points'])
                            except ValueError:
                                if not args.retry_failed or args.cached_only: raise
                                response=None
                        if response is None:
                            if args.cached_only: raise ValueError('No usable cached response; no API requested')
                            if examples is None:
                                frozen=None
                                if experiment!='full':
                                    # Prefer this experiment's frozen copy on resume; never mutate Full outputs.
                                    candidates=[destination/'retrieval.json',full_output/source.name/'retrieval.json',
                                                regular_output/source.name/'retrieval.json']
                                    frozen=next((p for p in candidates if p.is_file()),None)
                                    if args.no_mask and frozen is None:
                                        raise ValueError('no-mask needs the Full retrieval.json for identical examples; '
                                                         'run Full for this sample first, or combine --no-retrieval')
                                examples,provenance=prepare_examples(c,(config_path.parent/c['data_root']).resolve(),
                                    metadata['episode_id'],metadata['instruction'],polylines,sizes,destination,
                                    frozen_cache=frozen)
                            if client is None: client=make_client(c,config_path.parent)
                            response=call_stage(client,c,examples+content,stage,previous,provenance)
                            if stage=='rough': rough_regenerated=True
                            if path.exists():
                                history=destination/'response_history';history.mkdir(exist_ok=True)
                                write_json(history/(stage+'_'+hashlib.sha256(path.read_bytes()).hexdigest()+'.json'),json.loads(path.read_text()))
                            write_json(path,response)
                        plan,points=check_proposal(response,c['output_points'])
                        stages[stage]={'response_id':response.get('response_id'),'prompt_version':response.get('prompt_version'),
                                       'fewshot':response.get('fewshot',{'applied':False,'reason':'legacy cached response'}),
                                       'connection_annotation':normalize_connections(plan.connections,len(points))[1]}
                        previous=response
                        (destination/f'{stage}_cot.md').write_text(plan.path_description+'\n\n'+json.dumps(plan.model_dump()['points'],ensure_ascii=False),encoding='utf-8')
                    points,indices,modes=interpolate_corners(points,plan.connections,c['output_points'])
                    export(source,destination,metadata,start,points,modes,indices,available,stages,args.end,c)
                    write_json(status_path,{'status':'complete','export_version':PROMPT_VERSION,**({'prediction_only':True,'prediction_schema':PREDICTION_SCHEMA} if args.prediction_only else {})})
                    if args.prediction_only: print(f'[RESULT] sample={metadata["episode_id"]} prediction_only=true',flush=True)
                except APIError as exc:
                    write_json(status_path,{'status':'api_error','type':type(exc).__name__,'http_status':getattr(exc,'status_code',None)})
                    raise RuntimeError('API error; stopped without additional calls. Check credentials/quota and resume.') from None
                except RuntimeError: raise
                except Exception as exc:
                    write_json(status_path,{'status':'failed','error_type':type(exc).__name__,'error':str(exc)})
                    tqdm.write(f'[FAILED] {source.name}: {exc}')
        finally: summarize(output,sources,args.end,c)
        completed=[]
        for source in selected:
            directory=output/source.name
            if (directory/'metadata.json').is_file() and (directory/'status.json').is_file():
                if json.loads((directory/'status.json').read_text()).get('status')=='complete':
                    completed.append(json.loads((directory/'metadata.json').read_text())['episode_id'])
        if completed:
            simulator=ROOT.parent/'12'/'^^'
            print('[NEXT] env_isaaclab 환경에서 실행. 시뮬레이터가 꺼져 있으면 별도 터미널:')
            print(shlex.join(['python',str(simulator/'run_welding_simulator.py')]))
            print('[NEXT] 시연 및 녹화:')
            print(shlex.join(['python',str(simulator/'run_welding_sample.py'),
                              '--model',str(output),'--sample',*completed,
                              '--duration-sec','30','--camera-distance-scale','0.7',
                              '--video-dir',str(ROOT.parent/'VIDEO'/'GPT_COT_SESSION' if args.cot_session else ROOT.parent/'VIDEO'/output.name),
                              '--wait']))


if __name__=='__main__': sys.exit(main())
