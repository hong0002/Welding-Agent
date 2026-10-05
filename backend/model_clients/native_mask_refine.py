"""Current edited F mask → owned Segment2 refinement session (never detection)."""
import hashlib
import json
from pathlib import Path
import subprocess
import time
from uuid import UUID, uuid4

import numpy as np
from PIL import Image

from backend.model_clients import native
from backend.model_clients.contracts import ModelFault, Provenance
from backend.model_clients.native_mask_refine_entry import VERSION, paths, root_api_key
from backend.services.components import detect_components
from backend.services.mask_service import validate_binary_mask
from backend.services.simulator_process import FileLease


def write(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,allow_nan=False,indent=2)


class NativeMaskRefinementClient:
    def __init__(self, runtime):
        self.runtime=runtime
        self.last_result=None

    def refine(self, image, current, metadata, *, instruction):
        r=self.runtime;s=r.settings
        self.last_result=None;r.last_display_capture=None
        binding=r.binding(image)
        context=image.info.get('refinement_context',{})
        if (s.backend!='native_v2' or binding.camera!='F' or metadata.view_id!='F'
                or metadata.scene_id!=context.get('scene_id') or metadata.id!=context.get('mask_id')
                or not context.get('job_id') or not instruction.strip() or len(instruction)>16000 or '\x00' in instruction):
            raise ModelFault('NATIVE_INPUT_MISMATCH')
        validate_binary_mask(current,image.size)
        config,_,_=r.configuration();mask_config=config['mask']
        if r.run is native.run_native:
            if not root_api_key(native.ROOT):
                raise ModelFault('MASK_REFINEMENT_NOT_CONFIGURED')
        width=mask_config.get('line_width_px',24)
        if type(width) is not int or not 1<=width<=256:raise ModelFault('MODEL_NOT_CONFIGURED')
        with r.lock:
            lease=None;directory=None;started=time.monotonic();record=None;exit_code=None
            try:
                key=hashlib.sha256(str(s.repository.resolve()).encode()).hexdigest()
                lease=FileLease(r.records/(key+'.lock'))
                directory=r.records/'refinement'/str(uuid4());directory.mkdir(parents=True,exist_ok=False)
                artifact_id=str(uuid4())
                # Pixel-only snapshots: do not forward EXIF/PNG text or PIL info.
                Image.frombytes('RGB',image.size,image.convert('RGB').tobytes()).save(directory/'F_rgb.png')
                Image.frombytes('L',current.size,current.tobytes()).save(directory/'F_current_mask.png')
                request=dict(operation='MASK_REFINE',sample_id=binding.sample_id,view='F',
                    instruction=instruction,model=str(mask_config.get('model','gpt-6-sol')),
                    reasoning_effort=str(mask_config.get('reasoning_effort','medium')),line_width_px=width)
                write(directory/'request.json',request)
                source=r.source_fingerprint();config_hash=native.sha256(s.native_config)
                worker=Path(__file__).with_name('native_mask_refine_entry.py')
                worker_hash=native.sha256(worker)
                input_hashes={name:native.sha256(directory/name) for name in ('request.json','F_rgb.png','F_current_mask.png')}
                # Original YOLO evidence is local lineage for a later explicit
                # Trajectory3 approval. It NEVER enters the refinement request.
                self._carry_yolo(directory,metadata,binding.sample_id)
                if (directory/'yolo/detections.json').is_file():
                    input_hashes['yolo/detections.json']=native.sha256(directory/'yolo/detections.json')
                command=[str(s.python),'-B','-u',str(worker),str(directory)]
                record=dict(schema_version=1,stage='segment',native_stack='native_v2_refinement',operation='MASK_REFINE',
                    artifact_id=artifact_id,directory=str(directory),sample_id=binding.sample_id,
                    job_id=str(context['job_id']),scene_id=str(metadata.scene_id),source_mask_id=str(metadata.id),
                    source_mask_pixels_sha256=hashlib.sha256(current.tobytes()).hexdigest(),
                    config_sha256=config_hash,source_sha256=source,worker_sha256=worker_hash,input_files=input_hashes,
                    external_inputs=['F_rgb','current_F_binary_mask','refinement_instruction'],reference_in_request=False,
                    cwd=str(s.repository),command=command)
                write(directory/'input_manifest.json',record)
                r.running=True
                diagnostics={'diagnostic_path':r.records/'diagnostics'/f'{artifact_id}.jsonl'} if r.run is native.run_native else {}
                exit_code,_=r.run(command,cwd=s.repository,timeout=s.timeout,**diagnostics)
                if (source!=r.source_fingerprint() or config_hash!=native.sha256(s.native_config)
                        or worker_hash!=native.sha256(worker)
                        or any(native.sha256(directory/n)!=h for n,h in input_hashes.items())):
                    raise ModelFault('NATIVE_INPUT_MISMATCH')
                if exit_code!=0:
                    status=directory/'worker_status.json'
                    if status.is_file() and native.read_json(status).get('code')=='MASK_REFINEMENT_NOT_CONFIGURED':
                        raise ModelFault('MASK_REFINEMENT_NOT_CONFIGURED')
                    raise ModelFault('MASK_REFINEMENT_PROCESS_FAILED')
                data=native.read_json(directory/'iteration_001/result.json')
                if any(data.get(k)!=v for k,v in dict(operation='MASK_REFINE',sample_id=binding.sample_id,
                        instruction=instruction,prompt_version=VERSION).items()):
                    raise ModelFault('MASK_REFINEMENT_OUTPUT_INVALID')
                if data.get('sdk_status')=='incomplete':raise ModelFault('MASK_REFINEMENT_OUTPUT_PARTIAL')
                if data.get('sdk_status')!='completed':raise ModelFault('MASK_REFINEMENT_OUTPUT_INVALID')
                paths(data['predictions']['F'],image.size)
                with Image.open(directory/'iteration_001/F_prediction.png') as source_image:refined=source_image.copy()
                try:validate_binary_mask(refined,image.size)
                except Exception:raise ModelFault('MASK_REFINEMENT_EMPTY_MASK' if not np.asarray(refined).any()
                                                 else 'MASK_REFINEMENT_OUTPUT_INVALID') from None
                removed=current.info.get('removed_pixels')
                if removed is not None and np.any(removed & (np.asarray(refined)==255)):
                    raise ModelFault('MASK_REFINEMENT_CONSTRAINT_VIOLATION')
                # One output component for each selected input region; never
                # accept an incomplete region set or a bridge between regions.
                before=detect_components(current,metadata.min_component_area)
                after=detect_components(refined,metadata.min_component_area)
                if not after.regions:raise ModelFault('MASK_REFINEMENT_EMPTY_MASK')
                mapped=[]
                for region in after.regions:
                    ids=set(before.labels[after.labels==region.region_id].tolist())-{-1}
                    if len(ids)!=1:raise ModelFault('MASK_REFINEMENT_OUTPUT_PARTIAL')
                    mapped.extend(ids)
                if len(mapped)!=len(set(mapped)) or set(mapped)!={v.region_id for v in before.regions}:
                    raise ModelFault('MASK_REFINEMENT_OUTPUT_PARTIAL')
                from backend.model_clients.native_approval import clipped_predictions
                try:
                    # Validation only; discard the returned clipping projection.
                    # The native vector is never rewritten by refinement.
                    clipped_predictions(data['predictions']['F'],refined,refined,after)
                except ModelFault:raise ModelFault('MASK_REFINEMENT_OUTPUT_INVALID') from None
                # Keep the model's raster and polylines mutually consistent:
                # approval must never pass a different vector to Trajectory3.
                expected=Image.new('L',image.size)
                from PIL import ImageDraw
                draw=ImageDraw.Draw(expected)
                for line in paths(data['predictions']['F'],image.size):
                    points=[(round(x),round(y)) for x,y in line]
                    draw.line(points,fill=255,width=width,joint='curve')
                    radius=max(1,width//2)
                    for x,y in (points[0],points[-1]):draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=255)
                if expected.tobytes()!=refined.tobytes():raise ModelFault('MASK_REFINEMENT_OUTPUT_INVALID')
                refined.info['model_provenance']=Provenance(artifact_id=artifact_id,model_name=request['model'],
                    model_version=VERSION,source_sha256=source,latency_ms=(time.monotonic()-started)*1000,
                    reference_mode='native',source_scene_id=metadata.scene_id,source_mask_id=metadata.id,
                    instruction=instruction,native_session_id=directory.name,native_source_artifact_id=artifact_id,
                    input_mask_sha256=input_hashes['F_current_mask.png'],
                    native_artifacts={p.relative_to(directory).as_posix():True for p in directory.rglob('*') if p.is_file()},
                    input_transform='Segment2 predict_camera conditioned on current F binary; no retrieval or detection')
                r.last_error=None
                return refined
            except subprocess.TimeoutExpired:
                r.last_error='MODEL_TIMEOUT';raise ModelFault(r.last_error) from None
            except ModelFault as exc:
                r.last_error=exc.code;raise
            except (OSError,ValueError,KeyError,TypeError,OverflowError):
                r.last_error='MASK_REFINEMENT_OUTPUT_INVALID';raise ModelFault(r.last_error) from None
            finally:
                if record is not None:
                    files={p.relative_to(directory).as_posix():native.sha256(p) for p in sorted(directory.rglob('*')) if p.is_file()}
                    elapsed=(time.monotonic()-started)*1000
                    record.update(files=files,exit_code=exit_code,latency_ms=elapsed)
                    write(r.records/f'{record["artifact_id"]}.json',record)
                    # Raw display survives all result/constraint validation failures.
                    self.last_result=native.NativeResult(directory,record['artifact_id'],{},config,elapsed,record['source_sha256'])
                r.running=False
                if lease:lease.close()

    def _carry_yolo(self, directory, metadata, sample_id):
        provenance=metadata.artifact.provenance if metadata.artifact else None
        if not provenance or not provenance.native_source_artifact_id:return
        try:
            record=native.read_json(self.runtime.records/f'{UUID(str(provenance.native_source_artifact_id))}.json')
            source=Path(record['directory']).resolve();name='yolo/detections.json'
            if record['stage']!='segment' or record['sample_id']!=sample_id:raise ValueError('lineage')
            if not source.is_relative_to(native.ROOT.resolve()):raise ValueError('owned source')
            if not (source/name).exists():return
            if native.sha256(source/name)!=record['files'][name]:raise ValueError('changed source')
            detection=native.read_json(source/name)
            if detection.get('sample_id')!=sample_id or detection.get('bbox_source')!='server_yolo':raise ValueError('identity')
            (directory/'yolo').mkdir()
            with (directory/name).open('xb') as stream:stream.write((source/name).read_bytes())
        except (OSError,ValueError,KeyError,TypeError):
            raise ModelFault('NATIVE_INPUT_MISMATCH') from None
