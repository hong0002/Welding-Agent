from backend.services.project_paths import native_parent
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
from backend.services.simulator2_contract import exact_assets, Simulator2ContractError
from backend.schemas import VLAResultSummary, FinalPredictionDisplay
from backend.services.final_prediction_proof import FRAME, verify_completed_gpt


@dataclass(frozen=True)
class GPTTrajectorySettings:
    repository: Path = native_parent(ROOT)/'vlm_final_gpt'
    python: Path = NATIVE_PYTHON
    config: Path = native_parent(ROOT)/'vlm_final_gpt/config.yaml'
    attempts: Path = ROOT/'.cache/native-models/gpt-trajectory'
    timeout: float = 900
    retrieval_mode: str = 'segment2_adapter'
    retrieval_config: Path = ROOT/'.cache/native-integration/configs/segment2.windows.yaml'

    @classmethod
    def from_env(cls):
        values=backend_env_values()
        def get(k, default): return os.getenv(k) or values.get(k) or default
        repo=Path(get('WELD_GPT_TRAJECTORY_REPO', str(cls.repository))).resolve()
        return cls(repository=repo, python=Path(get('WELD_GPT_TRAJECTORY_PYTHON',str(cls.python))).resolve(),
                   config=Path(get('WELD_GPT_TRAJECTORY_CONFIG',str(repo/'config.yaml'))).resolve(),
                   retrieval_mode=get('WELD_GPT_RETRIEVAL_MODE','segment2_adapter'),
                   retrieval_config=Path(get('WELD_GPT_RETRIEVAL_CONFIG',str(cls.retrieval_config))).resolve())


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
        if self.execute is run_native and (s.python.resolve()!=NATIVE_PYTHON.resolve() or s.repository.resolve()!=(native_parent(ROOT)/'vlm_final_gpt').resolve()):
            raise GuidedVLAError('GPT_TRAJECTORY_CONFIGURATION_INVALID')
        try:
            c=yaml.safe_load(s.config.read_text(encoding='utf-8-sig'))
            if c['output_points']!=33 or not 2<=c['rough_points']<=33 or not c['model']:
                raise ValueError('Native counts/config')
            for key in ('server','retrieval','api_keys_path','reasoning_effort','max_output_tokens','timeout_sec','max_retries','image_max_side'):
                c[key]
            from backend.model_clients.gpt_trajectory_retrieval import configuration, RetrievalError
            try:c['_retrieval_files']=configuration(s.retrieval_mode,s.retrieval_config)
            except (OSError,KeyError,TypeError,ValueError,yaml.YAMLError):
                # Retrieval failure may downgrade visualization; never robot proof.
                c['_retrieval_files']=configuration('none',s.retrieval_config)
            if not backend_env_values().get('OPENAI_API_KEY'):
                raise GuidedVLAError('GPT_TRAJECTORY_TOKEN_REQUIRED')
            return c
        except (OSError,KeyError,TypeError,ValueError,yaml.YAMLError):
            raise GuidedVLAError('GPT_TRAJECTORY_CONFIGURATION_INVALID') from None

    def status(self):
        try: c=self.configuration(); code=None
        except GuidedVLAError as exc: c={}; code=exc.code
        return dict(backend='gpt',source='vlm_final_gpt',provider='gpt',model=c.get('model'),
                    configured=code is None,ready=code is None,state='READY' if code is None else 'NOT_CONFIGURED',
                    code=code,reference_mode='native',mask_views=['F','R','S4'],retrieval_mode=self.settings.retrieval_mode)

    def check_server(self):
        self.configuration()  # Configuration only; no health or paid inference request.
        return self.status()

    def validate_inputs(self, storage, job):
        values=self.input_validator.validate_inputs(storage,job)
        _, source, *_=values
        if set(source['images'])!=set(CAMERAS): raise GuidedVLAError('GPT_TRAJECTORY_INPUT_INVALID')
        try:h5,obj=exact_assets(source['dataset_root'],job.scene.sample_id)
        except Simulator2ContractError:raise GuidedVLAError('GPT_TRAJECTORY_SAMPLE_ASSET_MISSING') from None
        if not h5.is_file() or not obj.is_file(): raise GuidedVLAError('GPT_TRAJECTORY_SAMPLE_ASSET_MISSING')
        return values

    def validate_visualization_inputs(self,storage,job,mask_conditioning_views=None):
        from backend.model_clients.gpt_mask_conditioning import inputs
        values=inputs(storage,job,mask_conditioning_views)
        try:exact_assets(values[0]['dataset_root'],job.scene.sample_id)
        except Simulator2ContractError:raise GuidedVLAError('GPT_TRAJECTORY_SAMPLE_ASSET_MISSING') from None
        return values

    def run(self, storage, job, mask_conditioning_views=None, instruction=None):
        self.last_display=None
        self.last_attempt_id=None
        source,split,masks=self.validate_visualization_inputs(storage,job,mask_conditioning_views)
        strict=False;rough=None;record={'files':{}}
        # The old exact F-only accepted-proof contract remains untouched.
        # Multiview/unapproved predictions have their own display-only lifecycle.
        if list(masks)==['F'] and job.mask and job.mask.approved and not instruction:
            try:
                mask,source,record,rough,split,markdown,direction,points=self.validate_inputs(storage,job)
                strict=True
            except GuidedVLAError:pass
        c=self.configuration()
        s=self.settings
        attempt=s.attempts.resolve()/str(uuid4()); attempt.mkdir(parents=True,exist_ok=False)
        self.last_attempt_id=UUID(attempt.name)
        artifact=uuid4()
        h5,obj=exact_assets(source['dataset_root'],job.scene.sample_id)
        write_json(attempt/'source_job.json',job.model_dump(mode='json'))
        for view,entry in masks.items():write_bytes(attempt/f'{view}_mask.png',Path(entry['path']).read_bytes())
        # Snapshots/provenance only. Neither T3 reference nor guidance is a new model input.
        if rough:
            for name in ('query_image_guidance_2d.json','reference_trajectory_3d.json'):
                write_bytes(attempt/name,(rough.directory/name).read_bytes())
        input_names=[f'{v}_mask.png' for v in masks]+(['query_image_guidance_2d.json','reference_trajectory_3d.json'] if rough else [])
        write_json(attempt/'worker_input.json',dict(attempt=str(attempt),repo=str(s.repository),config=str(s.config),
            dataset_root=source['dataset_root'],images=source['images'],label=split['label'],instruction=instruction or (job.instruction.text if job.instruction else '선택한 마스크의 용접 이음선을 따라 최종 3D 궤적을 예측한다.'),
            mask_views=list(masks),mask_provenance={v:e['provenance'] for v,e in masks.items()},
            retrieval_polylines={v:[rough.image_guidance_2d['segments'][0]['points_pixel']] if v=='F' and rough else [] for v in CAMERAS},h5=str(h5),
            sample_id=job.scene.sample_id,split=job.scene.split,artifact_id=str(artifact),
            retrieval_mode=s.retrieval_mode,retrieval_config=str(s.retrieval_config)))
        manifest=dict(schema_version=1,backend='gpt',source='vlm_final_gpt',provider='gpt',artifact_id=str(artifact),
            attempt_id=attempt.name,sample_id=job.scene.sample_id,split=job.scene.split,mask_views=list(masks),mask_inputs=masks,visualization_only=not strict,
            workflow_job_id=str(job.id),workflow_conditioning_sha256=conditioning_hash(job),
            source_job=str(attempt/'source_job.json'),source_job_sha256=sha256(attempt/'source_job.json'),
            source_mask=next(iter(masks.values()))['path'],source_mask_id=next(iter(masks.values()))['id'],
            source_mask_sha256=next(iter(masks.values()))['sha256'],approved_at=next(iter(masks.values()))['approved_at'],
            scene_source_sha256=source['hashes'],scene_normalized_sha256=source['normalized_hashes'],
            rough_session=str(rough.directory) if rough else None,rough_source_files=record['files'],
            reference_in_request=False,trajectory3_guidance_in_request=False,
            files={name:sha256(attempt/name) for name in (*input_names,'worker_input.json')},
            h5=str(h5),h5_sha256=sha256(h5),obj=str(obj),obj_sha256=sha256(obj),
            native_files={name:sha256(s.repository/name) for name in ('predict.py','interpolate.py')},
            native_config_sha256=sha256(s.config),retrieval_mode=s.retrieval_mode,
            retrieval_implementation_files=c.get('_retrieval_files',{}),
            adapter_files={str(p):sha256(p) for p in (Path(__file__).with_name('gpt_trajectory_entry.py'),
                Path(__file__).with_name('gpt_trajectory_retrieval.py'))},sdk_max_retries=0,
            is_robot_executable=False,live_called=False)
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
            if any(sha256(p)!=h for p,h in {**manifest['adapter_files'],**manifest['retrieval_implementation_files']}.items()):
                raise ValueError('Retrieval/adapter source changed')
            from backend.model_clients.gpt_trajectory_retrieval import verify_provenance
            provenance=read_json(attempt/'retrieval_provenance.json')
            verify_provenance(provenance,job.scene.sample_id,source['dataset_root'],provenance['mode'])
            if provenance.get('visualization_only'):raise ValueError('Fallback is visualization only')
            response=read_json(attempt/'response.json')
            if response.get('artifact_id')!=str(artifact):raise ValueError('Wrong prediction artifact identity')
            self.validate_output(response,job)
            if not strict:
                # Complete native geometry is visible without claiming an approved F proof.
                write_json(attempt/'validation.json',dict(status='DISPLAY_ONLY',code='GPT_MULTIVIEW_VISUALIZATION_ONLY',xyz_modified=False))
                if display:display.validation_status='UNVALIDATED'
                raise GuidedVLAError('GPT_MULTIVIEW_VISUALIZATION_ONLY')
            from backend.services.final_prediction_arrays import verify_gpt_arrays
            verify_gpt_arrays(attempt,response,manifest)
            write_json(attempt/'completion.json',dict(attempt_id=attempt.name,response_validated=True,
                files={name:sha256(attempt/name) for name in ('response.json','trajectory.npz','metadata.json')}))
            verify_completed_gpt(attempt,manifest,job.model_dump(mode='json'))
            self.validate_inputs(storage,job)
            write_json(attempt/'validation.json',dict(status='PASS',workspace_bounds='NOT_SPECIFIED_BY_NATIVE_CONTRACT',
                continuity='single_native_weld_segment',mask_guidance='existing_approved_F_gate',xyz_modified=False))
            proof_files={p.relative_to(attempt).as_posix():sha256(p) for p in attempt.rglob('*') if p.is_file()}
            storage._write_json(storage.artifact_path('native_context',artifact,'.vla.json'),json.dumps(dict(
                directory=str(attempt),attempt_id=attempt.name,job_id=str(job.id),files=proof_files)))
            if display: display.validation_status='PASS';display.simulator_eligible=True
            return VLAResultSummary(artifact_id=artifact,attempt_id=UUID(attempt.name),sample_id=job.scene.sample_id,split=job.scene.split,
                model=response.get('model',c['model']),point_count=33,coordinate_frame=FRAME,ade_mm=response['ade_mm'],fde_mm=response['fde_mm'],
                mask_views=['F'],source='vlm_final_gpt',provider='gpt',raw_output_ref=str(artifact),retrieval_mode=s.retrieval_mode)
        except (OSError,ValueError,KeyError,TypeError):
            if not (attempt/'validation.json').exists(): write_json(attempt/'validation.json',{'status':'FAIL','code':'GPT_TRAJECTORY_OUTPUT_INVALID','xyz_modified':False})
            failure='GPT_TRAJECTORY_PROCESS_FAILED' if code!=0 else 'GPT_TRAJECTORY_OUTPUT_INVALID'
            try:
                worker_code=read_json(attempt/'worker_status.json').get('code')
                if worker_code in ('GPT_TRAJECTORY_RETRIEVAL_FAILED','GPT_TRAJECTORY_KNOWN_START_INVALID'):failure=worker_code
            except (OSError,ValueError):pass
            raise GuidedVLAError(failure) from None

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
        from backend.model_clients.geometry_display import finite_runs
        stages=[];policy={}
        if (attempt/'coordinate_policy.json').is_file():policy=read_json(attempt/'coordinate_policy.json')
        for name,label in (('rough.json','GPT Rough'),('raw_partial_rough.json','Raw Partial Rough'),
                ('derived_visualization.json','GPT Rough Derived Visualization'),
                ('corners.json','GPT Corners'),('raw_partial_corners.json','Raw Partial Corners'),
                ('response.json','GPT Final 33')):
            file=attempt/name
            if not file.is_file() or file.stat().st_size>4*1024*1024:continue
            try:
                raw=read_json(file)
                proposal=raw.get('proposal') or {}
                points=raw.get('predicted_path_xyz_mm',proposal.get('points',[]))
                frame=raw.get('coordinate_frame','source_robot_start_relative_mm')
                if frame not in (FRAME,'source_robot_start_relative_mm','gpt_start_relative_visualization_mm'):frame='unknown'
                units=raw.get('units','mm')
                if units not in ('mm','m'):units='unknown'
                runs,omitted=finite_runs(points,connections=raw.get('connections',proposal.get('connections')))
                foreign=raw.get('sample_id',job.scene.sample_id)!=job.scene.sample_id
                stages.append(dict(stage=label,coordinate_frame=frame,units=units,runs=runs,
                    omitted_point_count=omitted,current_overlay_allowed=not foreign,
                    sample_id=raw.get('sample_id',job.scene.sample_id)))
            except (OSError,ValueError,KeyError,TypeError,OverflowError):continue
        if not stages:return None
        selected=next((v for v in reversed(stages) if v['runs']),stages[-1])
        runs=selected['runs'];frame=selected['coordinate_frame'];units=selected['units']
        payload=dict(artifact_id=str(artifact),job_id=str(job.id),sample_id=job.scene.sample_id,
            conditioning_sha256=conditioning_hash(job),coordinate_frame=frame,units=units,runs=runs,
            stages=stages,selected_stage=selected['stage'],current_overlay_allowed=selected['current_overlay_allowed'])
        write_json(attempt/'display.json',payload)
        return FinalPredictionDisplay(artifact_id=artifact,source='vlm_final_gpt',provider='gpt',
            mask_views=read_json(attempt/'request_manifest.json').get('mask_views',[]) if (attempt/'request_manifest.json').is_file() else [],
            mask_provenance={v:e['provenance'] for v,e in read_json(attempt/'request_manifest.json').get('mask_inputs',{}).items()} if (attempt/'request_manifest.json').is_file() else {},
            retrieval_mode=(read_json(attempt/'request_manifest.json').get('retrieval_mode')
                if (attempt/'request_manifest.json').is_file() else None),
            displayable=bool(runs),point_count=sum(map(len,runs)),omitted_point_count=selected['omitted_point_count'],
            coordinate_frame=frame,units=units,raw_output_ref=str(artifact),validation_status='FAIL',
            simulator_eligible=False,display_ready=bool(runs),known_start_valid=policy.get('known_start_valid',True),
            coordinate_mode='absolute' if frame==FRAME else 'relative_visualization' if 'relative' in frame else 'raw',
            stages=[v['stage'] for v in stages],
            display_url=f'/api/weld/{job.id}/final-trajectory/{artifact}/display',
            display_sha256=digest(json.dumps(payload,sort_keys=True,allow_nan=False).encode()),attempt_id=UUID(attempt.name))

    def read_display(self,storage,job,artifact):
        d=job.raw_final_prediction
        stale=False
        if not d or d.artifact_id!=artifact:
            entry=next((v for v in job.previous_outputs if v['stage']=='final' and v['id']==str(artifact)),None)
            if not entry:raise GuidedVLAError('FINAL_TRAJECTORY_DISPLAY_STALE')
            d=FinalPredictionDisplay.model_validate(entry['output']);stale=True
        path=self.settings.attempts.resolve()/str(d.attempt_id)/'display.json'
        value=read_json(path)
        from backend.model_clients.guided_vla import digest
        if (value['job_id']!=str(job.id) or value['artifact_id']!=str(artifact)
            or digest(json.dumps(value,sort_keys=True,allow_nan=False).encode())!=d.display_sha256):
            raise GuidedVLAError('FINAL_TRAJECTORY_DISPLAY_STALE')
        stale=stale or value['conditioning_sha256']!=conditioning_hash(job)
        result={k:value[k] for k in ('artifact_id','coordinate_frame','units','runs')}
        result.update(stages=value.get('stages',[]),stale=stale,
            current_overlay_allowed=not stale and value.get('current_overlay_allowed',True))
        return result

    def verify_current(self,storage,job):
        r=job.vla_prediction
        if not r or r.source!='vlm_final_gpt':raise GuidedVLAError('FINAL_TRAJECTORY_BACKEND_MISMATCH')
        attempt=self.settings.attempts.resolve()/str(r.attempt_id)
        try:
            proof=read_json(storage.artifact_path('native_context',r.artifact_id,'.vla.json'))
            if proof['job_id']!=str(job.id) or Path(proof['directory']).resolve()!=attempt:raise ValueError('Identity')
            if any(sha256(attempt/n)!=h for n,h in proof['files'].items()):raise ValueError('Proof')
            manifest=read_json(attempt/'request_manifest.json')
            verify_completed_gpt(attempt,manifest,job.model_dump(mode='json'))
            if manifest.get('retrieval_mode') is not None:
                from backend.model_clients.gpt_trajectory_retrieval import verify_provenance
                source=read_json(storage.artifact_path('native_context',job.id,'.scene.json'))
                verify_provenance(read_json(attempt/'retrieval_provenance.json'),job.scene.sample_id,
                                  source['dataset_root'],manifest['retrieval_mode'])
            from backend.services.final_prediction_arrays import verify_gpt_arrays
            verify_gpt_arrays(attempt,read_json(attempt/'response.json'),read_json(attempt/'request_manifest.json'))
            self.validate_inputs(storage,job)
            return r
        except (OSError,ValueError,KeyError,TypeError):raise GuidedVLAError('GUIDED_VLA_ATTEMPT_CHANGED') from None
