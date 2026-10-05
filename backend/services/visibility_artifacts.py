"""Read owned historical XYZ evidence. No acceptance, SDK, retrieval or IK calls."""
import json
import re
import zipfile
from pathlib import Path
from uuid import UUID
import numpy as np
from backend.model_clients.config import ROOT
from backend.model_clients.geometry_display import finite_runs,presentation


def read_json(path):
    path=Path(path)
    if path.stat().st_size>16_000_000:raise ValueError('DISPLAY_FILE_TOO_LARGE')
    value=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value,dict):raise ValueError('DISPLAY_DATA_UNREADABLE')
    return value


def gpt_display(job,display,*,project=ROOT):
    from backend.model_clients.guided_vla import digest
    from backend.model_clients.guided_workflow import conditioning_hash
    file=owned(Path(project)/'.cache/native-models/gpt-trajectory'/str(display.attempt_id)/'display.json',Path(project)/'.cache/native-models/gpt-trajectory')
    value=read_json(file)
    if (value.get('job_id')!=str(job.id) or value.get('artifact_id')!=str(display.artifact_id)
            or digest(json.dumps(value,sort_keys=True,allow_nan=False).encode())!=display.display_sha256):
        raise ValueError('DISPLAY_EVIDENCE_INVALID')
    stale=not job.raw_final_prediction or job.raw_final_prediction.artifact_id!=display.artifact_id or value.get('conditioning_sha256')!=conditioning_hash(job)
    return {k:value.get(k,[]) if k in ('runs','stages') else value.get(k) for k in ('runs','stages','coordinate_frame','units')}|dict(stale=stale,current_overlay_allowed=not stale and value.get('current_overlay_allowed',True))


def owned(path,root):
    result=Path(path).resolve()
    if not result.is_relative_to(Path(root).resolve()):raise ValueError('DISPLAY_SOURCE_UNOWNED')
    return result


def xyz_npz(file,key):
    if file.stat().st_size>16_000_000:raise ValueError('DISPLAY_FILE_TOO_LARGE')
    with zipfile.ZipFile(file) as archive:
        if archive.getinfo(key+'.npy').file_size>4_000_000:raise ValueError('DISPLAY_FILE_TOO_LARGE')
    with np.load(file,allow_pickle=False) as value:
        a=value[key]
        if a.dtype.kind not in 'fiu' or a.ndim!=2 or a.shape[1]!=3 or len(a)>4096:
            raise ValueError('DISPLAY_DATA_UNREADABLE')
        return finite_runs(a.tolist())[0]


def prediction_rows(storage,job,*,project=ROOT):
    """Recover old completed/rejected sources by owned job receipt, not current state."""
    project=Path(project).resolve();rows=[]
    current=job.vla_prediction
    archived={e['id']:e['output'] for e in job.previous_outputs if e['stage']=='prediction'}
    bound=dict(archived)
    if current:bound[str(current.artifact_id)]=current.model_dump(mode='json')
    records=set((storage.root/'native_context').glob('*.vla.json'))
    records.update(storage.artifact_path('native_context',UUID(a),'.vla.json') for a in bound)
    for record_file in sorted(records):
        receipt=None
        try:
            artifact=str(UUID(record_file.name.removesuffix('.vla.json')))
            unverified=False
            try:receipt=read_json(record_file)
            except (OSError,ValueError,TypeError):
                summary=bound.get(artifact)
                if not summary:continue
                # Stored job lineage identifies the owned source even when an
                # acceptance receipt is missing/corrupt. Never grant proof authority.
                backend='gpt-trajectory' if summary['source']=='vlm_final_gpt' else 'guided-vla'
                attempt=str(UUID(summary['attempt_id']))
                receipt=dict(job_id=str(job.id),directory=str(project/'.cache/native-models'/backend/attempt),files={})
                unverified=True
            if receipt.get('job_id')!=str(job.id):continue
            directory=owned(receipt['directory'],project/'.cache/native-models')
            if directory.parent.name not in ('guided-vla','gpt-trajectory'):continue
            source='Guided VLA' if directory.parent.name=='guided-vla' else 'GPT Source'
            summary=bound.get(artifact,{})
            runs=[];frame=summary.get('coordinate_frame','unknown');units='unknown';sample=summary.get('sample_id',job.scene.sample_id)
            if (directory/'response.json').is_file():
                try:data=read_json(directory/'response.json')
                except (OSError,ValueError,TypeError):data={}
                runs=finite_runs(data.get('predicted_path_xyz_mm'),connections=data.get('connections'))[0]
                frame=data.get('coordinate_frame','unknown');units='mm'
                declared=data.get('sample_id',sample)
                sample=declared if isinstance(declared,str) and re.fullmatch(r'[A-Za-z0-9_]{1,128}',declared) else None
            # Guided playback's immutable numeric source is the stored NPZ.
            # Re-parsing server decimal mm JSON differs from its float32 meter
            # package by up to an ULP; selection must display those exact bytes.
            # Raw server response remains preserved, and no tolerance is relaxed.
            if (not runs or directory.parent.name=='guided-vla') and (directory/'trajectory.npz').is_file():
                runs=xyz_npz(directory/'trajectory.npz','predicted_path_m');units='m'
            if frame=='unknown' and (directory/'metadata.json').is_file():
                try:frame=read_json(directory/'metadata.json').get('coordinate_frame','unknown')
                except (OSError,ValueError,TypeError):pass
            stale=not current or str(current.artifact_id)!=artifact
            warnings=['UNVERIFIED_SOURCE_EVIDENCE'] if unverified else []
            from backend.model_clients.native import sha256
            try:
                if any(sha256(owned(directory/n,directory))!=h for n,h in receipt.get('files',{}).items()):
                    warnings.append('UNVERIFIED_SOURCE_EVIDENCE')
            except (OSError,ValueError):warnings.append('UNVERIFIED_SOURCE_EVIDENCE')
            rows.append(dict(id=artifact,stage='prediction',label=source+' · source trajectory',dimensions=3,
                stale=stale,sample_id=sample,current_overlay_allowed=not stale and sample==job.scene.sample_id,
                coordinate_frame=frame if frame in ('source_robot_frame_unaligned_with_isaac','source_robot_start_relative_mm','gpt_start_relative_visualization_mm') else 'unknown',units=units,runs=runs,
                states=presentation(exists=True,renderable=bool(runs),validated=not warnings and (bool(current and str(current.artifact_id)==artifact) or artifact in archived),
                    simulation=bool(runs),stale=stale),warnings=warnings))
        except (OSError,ValueError,KeyError,TypeError,zipfile.BadZipFile):
            # An associated unreadable receipt remains visible as an error card.
            if receipt and receipt.get('job_id')==str(job.id):
                rows.append(dict(id=record_file.name.removesuffix('.vla.json'),stage='prediction',label='Prediction source',dimensions=3,
                    stale=True,states=presentation(exists=True,renderable=False,stale=True),warnings=['DISPLAY_DATA_UNREADABLE']))
    return rows


def simulator_rows(job,*,project=ROOT):
    project=Path(project).resolve();root=project/'.cache/simulator/current-previews';rows=[]
    for session in sorted((root/'sessions').glob('*')):
        try:
            UUID(session.name);session=owned(session,root/'sessions');catalog=read_json(session/'catalog.json')
        except (OSError,ValueError,TypeError):continue
        for request in sorted((session/'queue').glob('*.json')):
            try:
                UUID(request.stem);command=read_json(request);claim=catalog[command['artifact_id']]
                descriptor=read_json(owned(claim['path'],root/'packages'))
                if descriptor.get('job_id')!=str(job.id):continue
                output=owned(session/'outputs'/request.stem,session)
                sources=[]
                if (output/'geometry.json').is_file():
                    try:
                        value=read_json(output/'geometry.json');runs=[]
                        for run in value.get('runs',[]):runs.extend(finite_runs(run)[0])
                    except (OSError,ValueError,TypeError):value={};runs=[]
                    sources.append(('simulator_source','Simulator source geometry',runs,value.get('coordinate_frame','unknown'),value.get('units','unknown')))
                if (output/'waypoints.npz').is_file():
                    if descriptor.get('robot_demo_only'):
                        try:
                            with np.load(output/'waypoints.npz',allow_pickle=False) as data:
                                points=data['demo_playback_points'];bounds=data['run_bounds']
                                runs=[]
                                for a,b in bounds:runs.extend(finite_runs(points[int(a):int(b)].tolist())[0])
                            sources.append(('playback','Demo transformed playback · SOURCE PRESERVED',runs,'robot_demo_scene','m'))
                        except (OSError,ValueError,TypeError,KeyError):
                            sources.append(('playback','Demo transformed playback',[],'robot_demo_scene','m'))
                    for key,label,frame in [('predicted_path_m','Simulator source trajectory',descriptor.get('coordinate_frame','unknown')),
                            ('playback_target_world_m','Derived playback trajectory','simulator_scene')]:
                        try:
                            runs=xyz_npz(output/'waypoints.npz',key)
                            sources.append(('simulator_source' if key=='predicted_path_m' else 'playback',label,runs,frame,'m'))
                        except KeyError:continue  # This array was never generated in this archive.
                        except (OSError,ValueError,TypeError,zipfile.BadZipFile):
                            sources.append(('simulator_source' if key=='predicted_path_m' else 'playback',label,[],frame,'m'))
                for stage,label,runs,frame,units in sources:
                    rows.append(dict(id=request.stem,stage=stage,label=label,dimensions=3,stale=True,
                        sample_id=descriptor['sample_id'],current_overlay_allowed=False,runs=runs,coordinate_frame=frame,units=units,
                        states=presentation(exists=True,renderable=bool(runs),simulation=bool(runs),stale=True),warnings=['SAVED_SIMULATOR_EVIDENCE']+([] if runs else ['NO_READABLE_FINITE_GEOMETRY'])))
            except (OSError,ValueError,KeyError,TypeError):continue
    return rows


def recovered_gpt_rows(job,known,*,project=ROOT):
    """Migration visibility for orphaned attempts; only public numeric stage fields."""
    rows=[]
    stages=(('rough.json','GPT Rough'),('raw_partial_rough.json','GPT Raw Partial Rough'),
        ('derived_visualization.json','GPT Rough Derived Visualization'),
        ('corners.json','GPT Corners'),('raw_partial_corners.json','GPT Raw Partial Corners'),('response.json','GPT Final'))
    for directory in sorted((Path(project)/'.cache/native-models/gpt-trajectory').glob('*')):
        try:
            UUID(directory.name);directory=owned(directory,Path(project)/'.cache/native-models/gpt-trajectory')
            manifest=read_json(directory/'request_manifest.json')
            if manifest.get('workflow_job_id')!=str(job.id):continue
            artifact=str(UUID(manifest['artifact_id']))
            if artifact in known:continue
            generated=False
            for index,(name,label) in enumerate(stages):
                if not (directory/name).is_file():continue
                try:
                    data=read_json(directory/name);proposal=data.get('proposal') or {}
                    runs=finite_runs(data.get('predicted_path_xyz_mm',proposal.get('points',[])),connections=data.get('connections',proposal.get('connections')))[0]
                    rows.append(dict(id=artifact,stage='gpt_stage',stage_index=index,label=label+' · recovered',dimensions=3,
                        stale=True,sample_id=manifest.get('sample_id'),current_overlay_allowed=False,runs=runs,
                        coordinate_frame=data.get('coordinate_frame') if data.get('coordinate_frame') in ('source_robot_frame_unaligned_with_isaac','source_robot_start_relative_mm','gpt_start_relative_visualization_mm') else 'unknown',
                        units=data.get('units') if data.get('units') in ('mm','m') else 'unknown',states=presentation(exists=True,renderable=bool(runs),simulation=bool(runs),stale=True),
                        warnings=['RECOVERED_RAW_SOURCE','UNVERIFIED_SOURCE_EVIDENCE']))
                    generated=True
                except (OSError,ValueError,KeyError,TypeError):
                    rows.append(dict(id=artifact,stage='gpt_stage',stage_index=index,label=label+' · unreadable',dimensions=3,
                        stale=True,sample_id=manifest.get('sample_id'),current_overlay_allowed=False,runs=[],coordinate_frame='unknown',units='unknown',
                        states=presentation(exists=True,renderable=False,stale=True),warnings=['DISPLAY_DATA_UNREADABLE']))
                    generated=True
            if not generated:
                rows.append(dict(id=directory.name,stage='attempt',label='NEW GPT OUTPUT · unavailable',stale=True,
                    states=presentation(exists=True,renderable=False,stale=True),warnings=['NO_GEOMETRY_GENERATED']))
        except (OSError,ValueError,KeyError,TypeError):continue
    return rows
