"""Owned TRAIN trajectory few-shots; never an implementation of the missing original.

Segment2 supplies image-retrieval candidates, not mask answers or query GT. The
reference action builder reads TRAIN H5 only. Local retrieval is a bounded,
documented heuristic; neither mode falls back to another mode.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import sys
import numpy as np
from PIL import Image
import yaml
from backend.model_clients.config import ROOT
from backend.model_clients.native import CAMERAS, read_json, sha256
from backend.services.scene_dataset import DatasetScenes
from backend.services.simulator2_contract import exact_assets

MODES = ('segment2_adapter', 'local', 'none')
VERSION = 'owned-train-trajectory-examples-v1'


class RetrievalError(ValueError):
    code = 'GPT_TRAJECTORY_RETRIEVAL_FAILED'


@contextmanager
def native_modules(repository, names):
    """Read-only imports scoped to the worker; no native main, downloads or API."""
    old_path = sys.path.copy(); old = {n:sys.modules.get(n) for n in names}
    old_bytecode=sys.dont_write_bytecode;sys.dont_write_bytecode=True
    sys.path.insert(0,str(repository))
    loaded = {}
    try:
        for name in names:
            spec = importlib.util.spec_from_file_location(name,repository/(name+'.py'))
            module = importlib.util.module_from_spec(spec);sys.modules[name]=module
            spec.loader.exec_module(module);loaded[name]=module
        yield loaded
    finally:
        sys.dont_write_bytecode=old_bytecode
        sys.path[:] = old_path
        for name, module in old.items():
            if module is None:sys.modules.pop(name,None)
            else:sys.modules[name]=module


def configuration(mode, segment_config):
    if mode not in MODES:raise RetrievalError('Invalid explicit retrieval mode')
    paths = [ROOT/'backend/model_clients/gpt_trajectory_retrieval.py']
    if mode != 'none':
        paths += [ROOT.parent/'vlm_segment2/mask_data.py',
                  ROOT.parent/'vlm_trajectory3/trajectory.py',ROOT.parent/'vlm_trajectory3/prepare_actions.py']
    if mode == 'segment2_adapter':
        paths += [ROOT.parent/'vlm_segment2/retrieval_client.py',Path(segment_config)]
        c = yaml.safe_load(Path(segment_config).read_text(encoding='utf-8-sig'))
        for key in ('ssh_alias','remote_root'):c['server'][key]
        c['retrieval']['remote_python'];c['yolo']['weights'];c['yolo']['remote_python']
        if c['retrieval'].get('bbox_source')!='server_yolo':raise RetrievalError('Database query forbidden')
    if any(not p.is_file() for p in paths):raise RetrievalError('Owned retrieval dependency missing')
    return {str(p.resolve()):sha256(p) for p in paths}


@dataclass(frozen=True)
class Query:
    sample_id: str
    instruction: str
    images: dict
    categories: dict
    polylines: dict
    sizes: dict
    mask: Path


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()


def category_text(categories):
    # Original dataset has no user instruction. Never pretend this is one.
    return ' '.join(str(categories.get(k,'')) for k in ('metal_position','parent_metal','object_size','metal_thickness'))


def text_similarity(a,b):
    aliases={'맞대기':'butt','모서리':'corner','겹치기':'lap','평판':'plate','원형':'round',
             '구조용':'structural','용접':'weld','왼쪽':'left','오른쪽':'right','위쪽':'top','아래쪽':'bottom'}
    def grams(value):
        value=value.lower()
        for k,v in aliases.items():value=value.replace(k,v)
        value=re.sub(r'\s+',' ',value)
        return {value[i:i+3] for i in range(max(0,len(value)-2))}
    x,y=grams(a),grams(b)
    return len(x&y)/max(1,(len(x)*len(y))**.5)


def category_similarity(a,b):
    keys=('metal_position','parent_metal','object_size','metal_thickness')
    return sum(str(a.get(k,'')).lower()==str(b.get(k,'')).lower() for k in keys)/len(keys)


def geometry(paths,size):
    arrays=[np.asarray(p,dtype=float)/np.asarray(size) for p in paths if len(p)>=2]
    if not arrays:return np.zeros(7)
    p=np.concatenate(arrays)
    if not np.isfinite(p).all():raise RetrievalError('Nonfinite query/reference geometry')
    return np.r_[p.mean(axis=0),np.ptp(p,axis=0),sum(np.linalg.norm(np.diff(a,axis=0),axis=1).sum() for a in arrays),
                 len(arrays)/10,1.]


def image_descriptor(path):
    with Image.open(path) as source:image=source.convert('RGB').resize((32,32))
    x=np.asarray(image,dtype=float)
    return np.concatenate([np.histogram(x[:,:,i],bins=16,range=(0,256),density=True)[0] for i in range(3)])


def load_reference(root,sample,c,*,action_builder=None):
    scene=DatasetScenes(root).resolve(sample)
    if scene.split!='train':raise RetrievalError('Reference must be TRAIN')
    h5,_=exact_assets(root,sample)
    label=read_json(scene.label)
    if label['info']['gid']!=sample:raise RetrievalError('Reference identity')
    if action_builder is None:
        with native_modules(ROOT.parent/'vlm_trajectory3',('trajectory','prepare_actions')) as modules:
            defaults=modules['trajectory'].SplitConfig()
            record=modules['prepare_actions'].build_record(scene.label,h5,'train',{
                'target_points':int(c['rough_points']), 'discontinuity':{
                    'absolute_jump_mm':defaults.absolute_jump,'relative_jump_ratio':defaults.relative_jump_ratio,
                    'duplicate_epsilon_mm':defaults.duplicate_epsilon}})
    else:record=action_builder(scene.label,h5,'train',c)
    if record['sample_id']!=sample or record['split']!='train':raise RetrievalError('Teaching binding')
    paths={v:[] for v in CAMERAS}
    for annotation in label.get('annotation_image',[]):
        for view in CAMERAS:
            if annotation.get('image_filename')==f'{sample}_{view}_Color.png':
                paths[view]=[l['points'] for l in annotation.get('image_label',[])
                             if l.get('label')=='full_welding' and l.get('type')=='polyline' and len(l.get('points',[]))>=2]
    source_files={str(p):sha256(p) for p in [scene.label,h5,*scene.images.values()]}
    return dict(sample_id=sample,scene=scene,label=label,paths=paths,record=record,h5=h5,source_files=source_files)


def select_segment2(query,c,segment_config,destination,*,native=None):
    settings=yaml.safe_load(Path(segment_config).read_text(encoding='utf-8-sig'))
    pool=max(int(c['retrieval']['top_k']),int(c['retrieval'].get('candidate_pool',20)))
    if not 1<=pool<=64:raise RetrievalError('Candidate pool exceeds bound')
    def select(module):
        server=settings['server'];retrieval=settings['retrieval'];yolo=settings['yolo']
        if retrieval.get('bbox_source')!='server_yolo':raise RetrievalError('Database query forbidden')
        cfg=module.RetrievalConfig(ssh_alias=server['ssh_alias'],remote_root=server['remote_root'],
            remote_python=retrieval['remote_python'],top_k=pool,bbox_source='server_yolo',
            yolo_python=yolo['remote_python'],yolo_weights=yolo['weights'],yolo_device=str(yolo.get('device','0')),
            confidence=float(yolo.get('confidence',.25)),margin=float(yolo.get('margin',.1)))
        return module.retrieve_sample(cfg,query.sample_id,images=query.images,output_dir=destination/'selection')
    if native is None:
        with native_modules(ROOT.parent/'vlm_segment2',('mask_data','retrieval_client')) as modules:
            module=modules['retrieval_client'];remote=module.remote_json
            # Fixed remote policy: reuse installed weights/cache, never download.
            module.remote_json=lambda config,command:remote(config,
                'export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1; '+command)
            result=select(module)
    else:result=select(native)
    if (str(result.get('index_split','')).lower() not in ('train','training') or
        result.get('bbox_source')!='server_yolo' or result.get('query_sample_id')!=query.sample_id or
        result.get('self_sample_excluded') is not True):raise RetrievalError('TRAIN/image-query proof required')
    ids=[];items=[]
    for rank,item in enumerate(result.get('results',[])[:pool],1):
        sample=item.get('sample_id');score=item.get('score')
        if (not isinstance(sample,str) or not re.fullmatch(r'[A-Za-z0-9_]{1,128}',sample) or
            sample==query.sample_id or sample in ids or type(score) not in (int,float) or
            not np.isfinite(score) or not -1.001<=score<=1.001):raise RetrievalError('Invalid native retrieval result')
        ids.append(sample);items.append(dict(sample_id=sample,native_rank=rank,image_score=float((score+1)/2)))
    if not items:raise RetrievalError('No native TRAIN candidates')
    # The complete native result is private, not Responses content.
    (destination/'selection').mkdir(exist_ok=True)
    (destination/'selection/retrieval.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return items


def select_local(query,root,c):
    """Bounded same-workpiece-family TRAIN labels only, then small RGB histogram."""
    family=query.sample_id.split('_')[:2]
    label_root=Path(root)/'2.데이터(NIA)/Training/02.라벨링데이터'
    if not label_root.is_dir():raise RetrievalError('TRAIN labels missing')
    candidates=[]
    # Directory levels only; never scan Validation or recurse through RGB/H5.
    for category in sorted(label_root.iterdir()):
        if not category.is_dir() or not category.name.startswith('TL_'):continue
        for thickness in sorted(category.iterdir()):
            if not thickness.is_dir():continue
            for directory in sorted(thickness.glob('_'.join(family)+'_*')):
                if not directory.is_dir():continue
                label=directory/(directory.name+'.json')
                if not label.is_file():continue
                if label.stem==query.sample_id:continue
                raw=read_json(label)
                if raw.get('info',{}).get('gid')!=label.stem:raise RetrievalError('Local label binding')
                meta=raw.get('categories',{})
                coarse=category_similarity(query.categories,meta)+text_similarity(query.instruction,category_text(meta))
                candidates.append((coarse,label.stem))
                if len(candidates)>=128:break
            if len(candidates)>=128:break
        if len(candidates)>=128:break
    if not candidates:raise RetrievalError('No local TRAIN candidates in bounded family')
    candidates.sort(key=lambda x:(-x[0],x[1]))
    pool=max(int(c['retrieval']['top_k']),int(c['retrieval'].get('candidate_pool',20)))
    if not 1<=pool<=64:raise RetrievalError('Candidate pool exceeds bound')
    a=image_descriptor(query.images['F']);items=[]
    for rank,(_,sample) in enumerate(candidates[:pool],1):
        scene=DatasetScenes(root).resolve(sample)
        if scene.split!='train':raise RetrievalError('Local reference is not TRAIN')
        b=image_descriptor(scene.images['F'])
        score=float(np.dot(a,b)/max(1e-15,np.linalg.norm(a)*np.linalg.norm(b)))
        items.append(dict(sample_id=sample,native_rank=rank,image_score=score))
    return items


def example_content(reference,c):
    record=reference['record'];sample=reference['sample_id'];scene=reference['scene']
    instruction=record['texts']['search_text_ko']
    # Correct answers are H5-derived teaching points, never a mask polyline.
    segments=record['rough_action']['segments'];points=[];connections=[]
    for segment in segments:
        values=segment['points_start_relative_mm']
        if points and values:connections.append('between_segments')
        for index,value in enumerate(values):
            if index:connections.append('within_segment')
            point=[float(value[k]) for k in ('x','y','z')] if isinstance(value,dict) else list(map(float,value))
            if len(point)!=3 or not np.isfinite(point).all():raise RetrievalError('Nonfinite TRAIN teaching')
            points.append(dict(zip(('x','y','z'),point)))
    if len(points)<2:raise RetrievalError('Empty TRAIN teaching')
    context=dict(reference_sample_id=sample,split='train',instruction=instruction,
        instruction_source='native_train_categories_and_h5_teaching_description',
        workpiece_metadata=reference['label'].get('categories',{}),
        coordinate_frame='retrieved_teaching_start_relative_mm',units='mm',registered_to_query=False,
        correct_teaching_answer=dict(path_description=record['texts']['action_text_ko'],points=points,
            connections=connections,uncertainties=[]))
    content=[dict(type='input_text',text=json.dumps(context,ensure_ascii=False,allow_nan=False))]
    with native_modules(ROOT.parent/'vlm_segment2',('mask_data',)) as modules:
        native=modules['mask_data']
        for view in CAMERAS:
            with Image.open(scene.images[view]) as source:image=source.convert('RGB')
            mask=native.rasterize(image.size,reference['paths'][view],int(c.get('mask_width_px',24)))
            image=native.overlay_mask(image,mask,(0,255,0),125)
            image.thumbnail((min(768,int(c['retrieval'].get('image_max_side',768))),)*2)
            buf=io.BytesIO();image.save(buf,format='JPEG',quality=90)
            content.extend([dict(type='input_text',text=f'TRAIN reference {sample}; camera {view}; green seam annotation'),
                dict(type='input_image',image_url='data:image/jpeg;base64,'+base64.b64encode(buf.getvalue()).decode(),detail='high')])
    return content


def prepare_examples(config,dataset_root,sample_id,instruction,polylines_by_camera,image_sizes,destination,
                     *,query,mode,segment_config,selector=None,reference_loader=None):
    destination=Path(destination);top_k=int(config['retrieval']['top_k'])
    if mode not in MODES or not 1<=top_k<=8 or query.sample_id!=sample_id:raise RetrievalError('Retrieval contract')
    if set(query.images)!=set(CAMERAS) or set(image_sizes)!=set(CAMERAS):raise RetrievalError('Nine-view query required')
    with Image.open(query.mask) as image:
        if image.mode!='L' or image.size!=tuple(image_sizes['F']) or not np.isin(np.asarray(image),[0,255]).all():
            raise RetrievalError('Current binary mask contract')
        foreground=np.argwhere(np.asarray(image)>0)
        if not len(foreground):raise RetrievalError('Empty approved mask')
        # Actual approved mask participates in ranking; not a query GT mask.
        mask_center=foreground[:,::-1].mean(axis=0)/np.asarray(image.size)
    provenance=dict(schema_version=1,implementation=VERSION,mode=mode,query_sample_id=sample_id,
        query_sources=['nine_view_rgb','approved_F_mask','user_instruction','trajectory3_2d_polylines','workpiece_categories'],
        query_gt_in_retrieval=False,query_gt_in_examples=False,top_k=top_k,split='train',
        query_image_hashes={v:sha256(p) for v,p in query.images.items()},query_mask_sha256=sha256(query.mask),
        query_instruction_sha256=digest(instruction),query_geometry_sha256=digest(polylines_by_camera),
        retrieved_sample_ids=[],references=[],source_files={})
    if mode=='none':
        provenance.update(implementation=VERSION+':explicit_none',warning='NO_RETRIEVAL_ACCURACY_UNVERIFIED')
    else:
        items=(selector(query,config) if selector else select_segment2(query,config,segment_config,destination)
               if mode=='segment2_adapter' else select_local(query,dataset_root,config))
        references=[];seen=set();qg=geometry(polylines_by_camera.get('F',[]),image_sizes['F'])
        for item in items:
            sample=item['sample_id']
            if sample==sample_id or sample in seen:raise RetrievalError('Self/duplicate sample excluded')
            seen.add(sample)
            ref=(reference_loader(dataset_root,sample,config) if reference_loader else load_reference(dataset_root,sample,config))
            if ref['scene'].split!='train':raise RetrievalError('Reference must be TRAIN')
            with Image.open(ref['scene'].images['F']) as image:size=image.size
            rg=geometry(ref['paths']['F'],size)
            geometry_score=float(np.exp(-np.linalg.norm(qg-rg)-np.linalg.norm(mask_center-rg[:2])))
            text_score=text_similarity(instruction,ref['record']['texts']['search_text_ko'])
            category_score=category_similarity(query.categories,ref['label']['categories'])
            score=.55*item['image_score']+.15*category_score+.15*text_score+.15*geometry_score
            references.append((score,sample,ref,dict(rank_native=item['native_rank'],image_score=item['image_score'],
                category_score=category_score,text_score=text_score,geometry_score=geometry_score,score=score)))
        references.sort(key=lambda v:(-v[0],v[1]))
        if len(references)<top_k:raise RetrievalError('Insufficient TRAIN references; no fallback')
        content=[]
        for rank,(_,sample,ref,scores) in enumerate(references[:top_k],1):
            folder=destination/'references'/sample;folder.mkdir(parents=True,exist_ok=False)
            (folder/'teaching_action.json').write_text(json.dumps(ref['record'],ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
            content.extend(example_content(ref,config))
            provenance['retrieved_sample_ids'].append(sample)
            provenance['references'].append(dict(sample_id=sample,split='train',rank=rank,**scores,
                label_sha256=sha256(ref['scene'].label),h5_sha256=sha256(ref['h5']),
                images_sha256={v:sha256(p) for v,p in ref['scene'].images.items()},
                teaching_action_sha256=sha256(folder/'teaching_action.json')))
            provenance['source_files'].update(ref['source_files'])
        provenance['implementation']+=':'+('vlm_segment2_image_selection_owned_rerank' if mode=='segment2_adapter' else 'bounded_local_histogram_ngram_geometry')
        provenance['dataset_sha256']=digest(provenance['source_files'])
        verify_provenance(provenance,sample_id,dataset_root,mode)
    (destination/'retrieval_provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return ([] if mode=='none' else content),provenance


def verify_provenance(value,sample,root,mode):
    if (value['query_sample_id']!=sample or value['mode']!=mode or value['split']!='train' or
        value['query_gt_in_retrieval'] is not False or value['query_gt_in_examples'] is not False):raise RetrievalError('Retrieval provenance')
    ids=value['retrieved_sample_ids']
    if sample in ids or len(ids)!=len(set(ids)) or (mode=='none' and ids):raise RetrievalError('Reference provenance')
    if mode!='none' and (not 1<=value['top_k']<=8 or len(ids)!=value['top_k'] or
        [r['sample_id'] for r in value['references']]!=ids or
        [r['rank'] for r in value['references']]!=list(range(1,len(ids)+1)) or
        any(r['split']!='train' for r in value['references']) or
        value.get('dataset_sha256')!=digest(value['source_files'])):
        raise RetrievalError('TRAIN proof')
    for path,hash_value in value['source_files'].items():
        p=Path(path).resolve()
        if not p.is_relative_to(Path(root).resolve()) or sha256(p)!=hash_value:raise RetrievalError('Reference source changed')


def owned_preparer(options):
    def prepare(c,root,sample,instruction,polylines,sizes,destination):
        categories=read_json(options['label']).get('categories',{})
        query=Query(sample,instruction,{v:Path(p) for v,p in options['images'].items()},categories,
                    polylines,sizes,Path(destination)/'F_mask.png')
        return prepare_visualization_examples(c,root,sample,instruction,polylines,sizes,destination,
            query=query,mode=options['retrieval_mode'],segment_config=options['retrieval_config'])
    return prepare


def prepare_visualization_examples(c,root,sample,instruction,polylines,sizes,destination,*,query,mode,segment_config,prepare=prepare_examples):
    """Explicit user-authorized fallback, without retrying any failed mode."""
    if mode not in MODES:raise RetrievalError('Invalid mode')
    chain=[]
    for actual in MODES[MODES.index(mode):]:
        folder=Path(destination)/'retrieval_attempts'/actual
        folder.mkdir(parents=True,exist_ok=False)
        try:
            content,provenance=prepare(c,root,sample,instruction,polylines,sizes,folder,
                query=query,mode=actual,segment_config=segment_config)
        except Exception:
            chain.append(dict(mode=actual,status='FAILED',code='GPT_TRAJECTORY_RETRIEVAL_FAILED'))
            (Path(destination)/'retrieval_chain.json').write_text(json.dumps(chain),encoding='utf-8')
            continue
        chain.append(dict(mode=actual,status='USED'))
        provenance.update(requested_mode=mode,fallback_chain=chain,visualization_only=actual!=mode)
        (Path(destination)/'retrieval_provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,allow_nan=False),encoding='utf-8')
        (Path(destination)/'retrieval_chain.json').write_text(json.dumps(chain),encoding='utf-8')
        return content,provenance
    raise RetrievalError('No visualization retrieval mode available')
