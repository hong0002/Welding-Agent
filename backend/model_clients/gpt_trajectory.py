"""Native vlm_final_gpt boundary. No new trajectory prompt or coordinate generation.

The fixed worker reuses native call_stage/check_proposal/interpolate_corners.
Current approved binary F replaces benchmark GT masks; other cameras are unlabeled.
Trajectory3 gates/binds the request, but its reference XYZ is never query XYZ.
"""
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4
import io
import json
import os
import subprocess
import numpy as np
import yaml
from backend.model_clients.config import ROOT
from backend.model_clients.native import NATIVE_PYTHON, CAMERAS, read_json, sha256
from backend.model_clients.native_process import run_native
from backend.model_clients.native_watchdog import WatchdogPolicy
from backend.model_clients.guided_workflow import WorkflowGuidedVLAClient, conditioning_hash
from backend.model_clients.guided_vla import GuidedVLAError, GuidedVLASettings, write_json, write_bytes
from backend.services.environment import backend_env_values
from backend.services.dataset_sample import exact_assets
from backend.schemas import VLAResultSummary, FinalPredictionDisplay
from backend.services.final_prediction_proof import FRAME, verify_completed_gpt


@dataclass(frozen=True)
class GPTTrajectorySettings:
    repository: Path = ROOT.parent/'vlm_final_gpt'
    python: Path = NATIVE_PYTHON
    config: Path = ROOT.parent/'vlm_final_gpt/config.yaml'
    attempts: Path = ROOT/'.cache/native-models/gpt-trajectory'
    timeout: float = 900

    @classmethod
    def from_env(cls):
        values=backend_env_values()
        def get(k, default): return os.getenv(k) or values.get(k) or default
        repo=Path(get('WELD_GPT_TRAJECTORY_REPO', str(cls.repository))).resolve()
        return cls(repository=repo, python=Path(get('WELD_GPT_TRAJECTORY_PYTHON',str(cls.python))).resolve(),
                   config=Path(get('WELD_GPT_TRAJECTORY_CONFIG',str(repo/'config.yaml'))).resolve())


class GPTTrajectoryPredictor:
    def __init__(self, settings=None, *, execute=run_native):
        self.settings=settings or GPTTrajectorySettings.from_env()
        self.execute=execute
        # Reuse only the read-only conditioning gate, with no VLA server/token config dependency.
        self.input_validator=WorkflowGuidedVLAClient(GuidedVLASettings(
            inputs=ROOT/'.cache/unused-guided-inputs.json',attempts=ROOT/'.cache/unused-guided-attempts'))
        self.last_display=None

    def configuration(self):
        s=self.settings
        if not all((s.repository/n).is_file() for n in ('predict.py','interpolate.py')) or not s.config.is_file():
            raise GuidedVLAError('GPT_TRAJECTORY_SOURCE_MISSING')
        if not s.python.is_file() or s.python.suffix.lower() not in ('.exe',''):
            raise GuidedVLAError('GPT_TRAJECTORY_PYTHON_MISSING')
        if not s.attempts.resolve().is_relative_to(ROOT.resolve()/'.cache'):
            raise GuidedVLAError('GPT_TRAJECTORY_CONFIGURATION_INVALID')
        if self.execute is run_native and (s.python.resolve()!=NATIVE_PYTHON.resolve() or s.repository.resolve()!=(ROOT.parent/'vlm_final_gpt').resolve()):
            raise GuidedVLAError('GPT_TRAJECTORY_CONFIGURATION_INVALID')
        # Required by predict.py at module import, even in its no-retrieval ablation.
        if not (s.repository.parent/'vlm_project2/fewshot_examples.py').is_file():
            raise GuidedVLAError('GPT_TRAJECTORY_RETRIEVAL_DEPENDENCY_MISSING')
        try:
            c=yaml.safe_load(s.config.read_text(encoding='utf-8-sig'))
            if c['output_points']!=33 or not 2<=c['rough_points']<=33 or not c['model']:
                raise ValueError('Native counts/config')
            for key in ('server','retrieval','api_keys_path','reasoning_effort','max_output_tokens','timeout_sec','max_retries','image_max_side'):
                c[key]
            if not (os.getenv('OPENAI_API_KEY') or backend_env_values().get('OPENAI_API_KEY') or
                    (s.config.parent/c['api_keys_path']).is_file()):
                raise GuidedVLAError('GPT_TRAJECTORY_TOKEN_REQUIRED')
            return c
        except (OSError,KeyError,TypeError,ValueError,yaml.YAMLError):
            raise GuidedVLAError('GPT_TRAJECTORY_CONFIGURATION_INVALID') from None

    def status(self):
        try: c=self.configuration(); code=None
        except GuidedVLAError as exc: c={}; code=exc.code
        return dict(backend='gpt',source='vlm_final_gpt',provider='gpt',model=c.get('model'),
                    configured=code is None,ready=code is None,state='READY' if code is None else 'NOT_CONFIGURED',
                    code=code,reference_mode='native',mask_views=['F'])

    def check_server(self):
        self.configuration()  # Configuration only; no health or paid inference request.
        return self.status()

    def validate_inputs(self, storage, job):
        values=self.input_validator.validate_inputs(storage,job)
        _, source, *_=values
        if set(source['images'])!=set(CAMERAS): raise GuidedVLAError('GPT_TRAJECTORY_INPUT_INVALID')
        h5,obj=exact_assets(source['dataset_root'],job.scene.sample_id)
        if not h5.is_file() or not obj.is_file(): raise GuidedVLAError('GPT_TRAJECTORY_SAMPLE_ASSET_MISSING')
        return values

    def run(self, storage, job):
        self.last_display=None
        mask,source,record,rough,split,markdown,direction,points=self.validate_inputs(storage,job)
        c=self.configuration()
        s=self.settings
        attempt=s.attempts.resolve()/str(uuid4()); attempt.mkdir(parents=True,exist_ok=False)
        artifact=uuid4()
        h5,obj=exact_assets(source['dataset_root'],job.scene.sample_id)
        write_json(attempt/'source_job.json',job.model_dump(mode='json'))
        write_bytes(attempt/'F_mask.png',storage.artifact_path('masks',job.mask.id).read_bytes())
        # Snapshots/provenance only. Neither T3 reference nor guidance is a new model input.
        for name in ('query_image_guidance_2d.json','reference_trajectory_3d.json'):
            write_bytes(attempt/name,(rough.directory/name).read_bytes())
        write_json(attempt/'worker_input.json',dict(attempt=str(attempt),repo=str(s.repository),config=str(s.config),
            dataset_root=source['dataset_root'],images=source['images'],label=split['label'],instruction=job.instruction.text,
            retrieval_polylines={v:[rough.image_guidance_2d['segments'][0]['points_pixel']] if v=='F' else [] for v in CAMERAS},h5=str(h5),
            sample_id=job.scene.sample_id,split=job.scene.split,artifact_id=str(artifact)))
        manifest=dict(schema_version=1,backend='gpt',source='vlm_final_gpt',provider='gpt',artifact_id=str(artifact),
            attempt_id=attempt.name,sample_id=job.scene.sample_id,split=job.scene.split,mask_views=['F'],
            workflow_job_id=str(job.id),workflow_conditioning_sha256=conditioning_hash(job),
            source_job=str(attempt/'source_job.json'),source_job_sha256=sha256(attempt/'source_job.json'),
            source_mask=str(storage.artifact_path('masks',job.mask.id)),source_mask_id=str(job.mask.id),
            source_mask_sha256=sha256(storage.artifact_path('masks',job.mask.id)),approved_at=job.mask.approved_at.isoformat(),
            scene_source_sha256=source['hashes'],scene_normalized_sha256=source['normalized_hashes'],
            rough_session=str(rough.directory),rough_source_files=record['files'],
            reference_in_request=False,trajectory3_guidance_in_request=False,
            files={name:sha256(attempt/name) for name in ('F_mask.png','query_image_guidance_2d.json','reference_trajectory_3d.json','worker_input.json')},
            h5=str(h5),h5_sha256=sha256(h5),obj=str(obj),obj_sha256=sha256(obj),
            native_files={name:sha256(s.repository/name) for name in ('predict.py','interpolate.py')},
            native_config_sha256=sha256(s.config),is_robot_executable=False,live_called=False)
        write_json(attempt/'request_manifest.json',manifest)
        # No browser or Agent-controlled executable/cwd/config arguments.
        write_json(attempt/'submission.json',dict(attempt_id=attempt.name,claimed=True,live_called=True))
        try:
            code,_=self.execute([str(s.python),'-B','-u','-X','utf8',str(ROOT/'backend/model_clients/gpt_trajectory_entry.py'),str(attempt/'worker_input.json')],
                                cwd=s.repository,timeout=s.timeout,preserve_openai_api_key=True,
                                # GPT stages do not emit Segment's F/R/S4 markers. Use
                                # the overall cap without a false 60-second setup stall.
                                watchdog_policy=WatchdogPolicy(setup=s.timeout,retrieval=s.timeout,model_stage=s.timeout))
            write_json(attempt/'process_exit.json',{'exit_code':code})
        except (OSError,subprocess.SubprocessError):
            code=-1; write_json(attempt/'process_exit.json',{'exit_code':None,'code':'GPT_TRAJECTORY_PROCESS_FAILED'})
        # Always preserve native raw stages, even when parsing/export/process fails.
        display=self.capture_display(attempt,artifact,job)
        self.last_display=display
        try:
            if code!=0: raise ValueError('Native process failed')
            if (sha256(s.config)!=manifest['native_config_sha256'] or
                any(sha256(s.repository/n)!=h for n,h in manifest['native_files'].items())):raise ValueError('Native source/config changed during execution')
            response=read_json(attempt/'response.json')
            if response.get('artifact_id')!=str(artifact):raise ValueError('Wrong prediction artifact identity')
            self.validate_output(response,job)
            from backend.services.final_prediction_arrays import verify_gpt_arrays
            verify_gpt_arrays(attempt,response,manifest)
            write_json(attempt/'completion.json',dict(attempt_id=attempt.name,response_validated=True,
                files={name:sha256(attempt/name) for name in ('response.json','trajectory.npz','metadata.json')}))
            verify_completed_gpt(attempt,manifest,job.model_dump(mode='json'))
            self.validate_inputs(storage,job)
            write_json(attempt/'validation.json',dict(status='PASS',workspace_bounds='NOT_SPECIFIED_BY_NATIVE_CONTRACT',
                continuity='single_native_weld_segment',mask_guidance='existing_approved_F_gate',xyz_modified=False))
            proof_files={p.name:sha256(p) for p in attempt.iterdir() if p.is_file()}
            storage._write_json(storage.artifact_path('native_context',artifact,'.vla.json'),json.dumps(dict(
                directory=str(attempt),attempt_id=attempt.name,job_id=str(job.id),files=proof_files)))
            if display: display.validation_status='PASS';display.simulator_eligible=True
            return VLAResultSummary(artifact_id=artifact,attempt_id=UUID(attempt.name),sample_id=job.scene.sample_id,split=job.scene.split,
                model=response.get('model',c['model']),point_count=33,coordinate_frame=FRAME,ade_mm=response['ade_mm'],fde_mm=response['fde_mm'],
                mask_views=['F'],source='vlm_final_gpt',provider='gpt',raw_output_ref=str(artifact))
        except (OSError,ValueError,KeyError,TypeError):
            if not (attempt/'validation.json').exists(): write_json(attempt/'validation.json',{'status':'FAIL','code':'GPT_TRAJECTORY_OUTPUT_INVALID','xyz_modified':False})
            raise GuidedVLAError('GPT_TRAJECTORY_PROCESS_FAILED' if code!=0 else 'GPT_TRAJECTORY_OUTPUT_INVALID') from None

    @staticmethod
    def validate_output(r,job):
        from backend.model_clients.trajectory_contracts import GPTPredictedTrajectory
        value=GPTPredictedTrajectory.model_validate(r)
        if value.sample_id!=job.scene.sample_id or value.split!=job.scene.split:raise ValueError('Sample differs')
        if any(v!='within_segment' for v in value.connections):raise ValueError('Disconnected/unknown geometry is display only')
        return value

    @staticmethod
    def capture_display(attempt,artifact,job):
        """Bounded raw finite runs; invalid numeric rows split paths rather than bridging."""
        from backend.model_clients.guided_vla import digest
        file=next((attempt/n for n in ('response.json','corners.json','rough.json') if (attempt/n).is_file()),None)
        if not file:return None
        try:
            raw=read_json(file)
            if file.name=='response.json':
                points=raw.get('predicted_path_xyz_mm',[]);frame=raw.get('coordinate_frame','unknown')
                units=raw.get('units','unknown')
            else:
                points=raw.get('proposal',{}).get('points',[]);frame='source_robot_start_relative_mm';units='mm'
            # Raw metadata is display-only. Do not relabel rejected units or expose
            # arbitrary strings from malformed output as frame/prompt text.
            if frame not in (FRAME,'source_robot_start_relative_mm'):frame='unknown'
            if units not in ('mm','m'):units='unknown'
            runs=[];current=[];omitted=0
            modes=raw.get('connections',raw.get('proposal',{}).get('connections',[]))
            if modes==['within_segment']:modes=['within_segment']*max(0,len(points)-1)
            if len(modes)!=len(points)-1:modes=['unknown']*max(0,len(points)-1)
            for index,p in enumerate(points[:4096]):
                if index and modes[index-1]!='within_segment' and current:
                    runs.append(current);current=[]
                p=[p.get(k) for k in ('x','y','z')] if isinstance(p,dict) else p
                if isinstance(p,(list,tuple)) and len(p)==3 and all(type(v) in (int,float) and np.isfinite(v) for v in p):current.append(p)
                else:
                    omitted+=1
                    if current:runs.append(current);current=[]
            if current:runs.append(current)
            # Raw response of another sample is retained privately but not rendered as this sample.
            if raw.get('sample_id',job.scene.sample_id)!=job.scene.sample_id:runs=[]
            payload=dict(artifact_id=str(artifact),job_id=str(job.id),conditioning_sha256=conditioning_hash(job),
                         coordinate_frame=frame,units=units,runs=runs)
            write_json(attempt/'display.json',payload)
            return FinalPredictionDisplay(artifact_id=artifact,source='vlm_final_gpt',provider='gpt',
                model=raw.get('model') if isinstance(raw.get('model'),str) and raw['model'].startswith('gpt-') and len(raw['model'])<128 and all(c.isalnum() or c in '-._' for c in raw['model']) else None,displayable=bool(runs),
                point_count=sum(map(len,runs)),omitted_point_count=omitted,coordinate_frame=frame,units=units,
                raw_output_ref=str(artifact),validation_status='FAIL',simulator_eligible=False,
                display_url=f'/api/weld/{job.id}/final-trajectory/{artifact}/display',
                display_sha256=digest(json.dumps(payload,sort_keys=True,allow_nan=False).encode()),attempt_id=UUID(attempt.name))
        except (OSError,ValueError,KeyError,TypeError,OverflowError):return None

    def read_display(self,storage,job,artifact):
        d=job.raw_final_prediction
        if not d or d.artifact_id!=artifact:raise GuidedVLAError('FINAL_TRAJECTORY_DISPLAY_STALE')
        path=self.settings.attempts.resolve()/str(d.attempt_id)/'display.json'
        value=read_json(path)
        from backend.model_clients.guided_vla import digest
        if (value['job_id']!=str(job.id) or value['artifact_id']!=str(artifact) or value['conditioning_sha256']!=conditioning_hash(job)
            or digest(json.dumps(value,sort_keys=True,allow_nan=False).encode())!=d.display_sha256):
            raise GuidedVLAError('FINAL_TRAJECTORY_DISPLAY_STALE')
        return {k:value[k] for k in ('artifact_id','coordinate_frame','units','runs')}

    def verify_current(self,storage,job):
        r=job.vla_prediction
        if not r or r.source!='vlm_final_gpt':raise GuidedVLAError('FINAL_TRAJECTORY_BACKEND_MISMATCH')
        attempt=self.settings.attempts.resolve()/str(r.attempt_id)
        try:
            proof=read_json(storage.artifact_path('native_context',r.artifact_id,'.vla.json'))
            if proof['job_id']!=str(job.id) or Path(proof['directory']).resolve()!=attempt:raise ValueError('Identity')
            if any(sha256(attempt/n)!=h for n,h in proof['files'].items()):raise ValueError('Proof')
            verify_completed_gpt(attempt,read_json(attempt/'request_manifest.json'),job.model_dump(mode='json'))
            from backend.services.final_prediction_arrays import verify_gpt_arrays
            verify_gpt_arrays(attempt,read_json(attempt/'response.json'),read_json(attempt/'request_manifest.json'))
            self.validate_inputs(storage,job)
            return r
        except (OSError,ValueError,KeyError,TypeError):raise GuidedVLAError('GUIDED_VLA_ATTEMPT_CHANGED') from None
