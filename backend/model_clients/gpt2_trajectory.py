from backend.services.project_paths import native_parent
"""Thin adapter to vlm_final_gpt2's original CLI; native owns all prediction math."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
from uuid import UUID, uuid4
import numpy as np
import yaml
from backend.model_clients.config import ROOT
from backend.model_clients.native import NATIVE_PYTHON, CAMERAS, sha256, read_json
from backend.model_clients.guided_vla import GuidedVLAError, write_json
from backend.model_clients.guided_workflow import conditioning_hash
from backend.model_clients.native_process import run_native
from backend.model_clients.native_watchdog import WatchdogPolicy
from backend.services.environment import backend_env_values
from backend.services.dataset_sample import exact_assets
from backend.services.gpt2_prediction_proof import FRAME, native_arrays, verify_completed_gpt2
from backend.schemas import FinalPredictionDisplay, VLAResultSummary


@dataclass(frozen=True)
class GPT2TrajectorySettings:
    repository: Path = native_parent(ROOT) / 'vlm_final_gpt2'
    python: Path = NATIVE_PYTHON
    config: Path = native_parent(ROOT) / 'vlm_final_gpt2/config.yaml'
    attempts: Path = ROOT / '.cache/native-models/gpt2-trajectory'
    shared_root: Path = native_parent(ROOT)
    baseline_root: Path | None = None
    retrieval_ssh_alias: str | None = None
    retrieval_mode: str = 'native'
    local_retrieval_root: Path | None = None
    local_retrieval_cache: Path | None = None
    timeout: float = 900

    @classmethod
    def from_env(cls, env_file=None):
        values = backend_env_values(env_file)
        def get(k, default): return os.getenv(k) or values.get(k) or default
        repo = Path(get('WELD_GPT2_TRAJECTORY_ROOT', str(cls.repository))).resolve()
        baseline = get('WELD_GPT2_BASELINE_ROOT', None)
        cache = get('WELD_GPT2_LOCAL_RETRIEVAL_CACHE', None)
        return cls(repository=repo, config=Path(get('WELD_GPT2_TRAJECTORY_CONFIG', str(repo/'config.yaml'))).resolve(),
                   shared_root=Path(get('WELD_GPT2_SHARED_ROOT', str(repo.parent))).resolve(),
                   baseline_root=Path(baseline).resolve() if baseline else None,
                   retrieval_ssh_alias=get('WELD_GPT2_RETRIEVAL_SSH_ALIAS', None),
                   retrieval_mode=get('WELD_GPT2_RETRIEVAL_MODE','local'),
                   local_retrieval_root=Path(get('WELD_GPT2_LOCAL_RETRIEVAL_ROOT',str(native_parent(ROOT)/'vlm_embedding_server'))).resolve(),
                   local_retrieval_cache=Path(cache).resolve() if cache else None)


class GPT2TrajectoryPredictor:
    def __init__(self, settings=None, *, execute=run_native):
        self.settings = settings or GPT2TrajectorySettings.from_env()
        self.execute = execute
        self.last_display = None
        self.last_attempt_id = None

    def config(self):
        s = self.settings
        try:
            c = yaml.safe_load(s.config.read_text(encoding='utf-8-sig'))
            if not 2 <= c['rough_points'] <= c['output_points'] <= 4096: raise ValueError('Counts')
            for k in ('model','reasoning_effort','api_keys_path','data_root','baseline_root','output_root',
                      'server','retrieval','max_output_tokens','timeout_sec','max_retries','image_max_side','mask_width_px'): c[k]
            return c
        except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError):
            raise GuidedVLAError('GPT2_CONFIGURATION_INVALID') from None

    def requirements(self):
        s = self.settings
        errors = []
        if s.retrieval_mode not in ('native','local'): errors.append('GPT2_CONFIGURATION_INVALID')
        if s.retrieval_mode == 'local' and (not s.local_retrieval_root or not all(
                (s.local_retrieval_root/n).is_file() for n in ('service/action_runtime.py','service/retrieve.py','service/__init__.py'))):
            errors.append('GPT2_LOCAL_RETRIEVAL_MISSING')
        if not all((s.repository/n).is_file() for n in ('predict.py','interpolate.py')): errors.append('GPT2_SOURCE_MISSING')
        if not s.python.is_file(): errors.append('GPT2_PYTHON_MISSING')
        if not s.attempts.resolve().is_relative_to(ROOT.resolve()/'.cache'): errors.append('GPT2_CONFIGURATION_INVALID')
        if self.execute is run_native and (s.repository.resolve() != (native_parent(ROOT)/'vlm_final_gpt2').resolve() or s.python != NATIVE_PYTHON):
            errors.append('GPT2_CONFIGURATION_INVALID')
        try: c = self.config()
        except GuidedVLAError as exc: return [*errors, exc.code]
        if not (s.shared_root/'vlm_project2/fewshot_examples.py').is_file(): errors.append('GPT2_NATIVE_RETRIEVAL_MISSING')
        try:
            if '--prediction-only' not in (s.repository/'predict.py').read_text(encoding='utf-8'):
                errors.append('GPT2_PREDICTION_ONLY_UNAVAILABLE')
        except (OSError,UnicodeError):
            if 'GPT2_SOURCE_MISSING' not in errors: errors.append('GPT2_SOURCE_MISSING')
        if self.execute is run_native and not backend_env_values().get('OPENAI_API_KEY'): errors.append('GPT2_TOKEN_REQUIRED')
        return errors

    def baseline(self, c): return self.settings.baseline_root or (self.settings.config.parent/c['baseline_root']).resolve()

    def configuration(self):
        errors = self.requirements()
        if errors: raise GuidedVLAError(errors[0])
        return self.config()

    def status(self):
        errors = self.requirements()
        try: c = self.config()
        except GuidedVLAError: c = {}
        # 'gpt' is the existing Agent intent/provider family, not the selector.
        return dict(backend='gpt',selector='gpt2',source='vlm_final_gpt2',provider='gpt',
                    model=c.get('model'),reasoning_effort=c.get('reasoning_effort'),point_count=c.get('output_points'),
                    configured=not errors,ready=not errors,state='NOT_CONFIGURED' if errors else 'READY',
                    code=errors[0] if errors else None,configuration_codes=errors,reference_mode='native',
                    retrieval_mode='native',mask_views=list(CAMERAS),web_masks_used_as_input=False,
                    retrieval_transport=self.settings.retrieval_mode,
                    ricl_required_by_model=False,baseline_dependency_scope='evaluation_only',
                    gt_metrics_optional=True,production_without_ricl=True,prediction_only=True)

    def snapshot_query(self, storage, job, *, instruction=None, dataset=None):
        from backend.model_clients.gpt2_query_snapshot import snapshot_current_query
        return snapshot_current_query(storage,job,self.settings.attempts.parent/'gpt2-query-inputs',
                                      instruction=instruction,dataset=dataset,project=ROOT)

    def check_server(self):
        self.configuration()
        return self.status()  # No health/inference/SSH call.

    def validate_visualization_inputs(self, storage, job, mask_conditioning_views=None):
        self.last_display = None
        self.last_attempt_id = None
        self.configuration()  # Fail admission before Workflow archives an existing result.
        try:
            if job.state.value not in ('MASK_READY','INSTRUCTION_READY','ROUGH_PATH_READY','VLA_READY'):
                raise ValueError('Native final admission state')
            if not job.scene.sample_id or not job.mask: raise ValueError('Current scene/mask required')
            source = read_json(storage.artifact_path('native_context', job.id, '.scene.json'))
            if set(source['images']) != set(CAMERAS) or source.get('sample_id') != job.scene.sample_id:
                raise ValueError('Current sample / 9 RGB required')
            if conditioning_hash(storage.get_job(job.id)) != conditioning_hash(job): raise ValueError('Current job changed')
            if any(sha256(source['images'][v]) != h for v,h in source['hashes'].items()): raise ValueError('Scene changed')
            if any(sha256(storage.artifact_path('scenes', job.scene.views[v].image_id)) != h for v,h in source['normalized_hashes'].items()):
                raise ValueError('Canvas scene changed')
            h5, obj = exact_assets(source['dataset_root'], job.scene.sample_id)
            if not h5.is_file() or not obj.is_file(): raise ValueError('Exact query asset missing')
            from backend.model_clients.gpt2_query_snapshot import validate_current_query
            validate_current_query(storage,job)
            return source, h5, obj
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise GuidedVLAError('GPT2_INPUT_INVALID') from None

    validate_inputs = validate_visualization_inputs

    def resolve_sample(self, job, h5, c):
        """Require a real native baseline export. Never synthesize its prediction/GT."""
        import h5py
        matches = []
        for p in self.baseline(c).glob('*/metadata.json'):
            try:
                m = read_json(p)
                if m.get('episode_id') == job.scene.sample_id: matches.append((p.parent,m))
            except (OSError,ValueError): continue
        if len(matches) != 1: raise GuidedVLAError('GPT2_NATIVE_SAMPLE_MISSING')
        directory, metadata = matches[0]
        split = str(metadata.get('split','')).lower()
        split = 'val' if split in ('validation','valid','val') else split
        try:
            if split != job.scene.split or metadata['source_units'] != 'mm' or metadata['coordinate_frame'] != FRAME:
                raise ValueError('Native sample frame/split')
            if not all((directory/n).is_file() for n in ('source_label.json','trajectory.npz',*[f'raw_rgb/{v}_Color.png' for v in CAMERAS])):
                raise ValueError('Incomplete baseline')
            from PIL import Image
            for v in CAMERAS:
                with Image.open(directory/'raw_rgb'/f'{v}_Color.png') as im:
                    view=job.scene.views[v]
                    if im.size!=(view.width,view.height):raise ValueError('Native label/RGB dimensions differ')
            start = np.asarray(metadata['start_xyz'], dtype=float)
            with h5py.File(h5,'r') as f:
                data = f['trajectory']
                if data.ndim != 2 or data.shape[0] < 2 or data.shape[1] < 3: raise ValueError('H5 XYZ')
                first = np.asarray(data[0,:3], dtype=float)
            if start.shape != (3,) or not np.isfinite(start).all() or not np.array_equal(start,first):
                raise GuidedVLAError('GPT2_KNOWN_START_INVALID')
            with np.load(directory/'trajectory.npz',allow_pickle=False) as arrays:
                for key in ('predicted_path_m','ground_truth_path_m'):
                    a = arrays[key]
                    if a.ndim != 2 or a.shape[1] != 3 or len(a) < 2 or not np.isfinite(a).all(): raise ValueError('Baseline array')
            return directory, metadata
        except GuidedVLAError: raise
        except (OSError,ValueError,KeyError,TypeError): raise GuidedVLAError('GPT2_NATIVE_INPUT_INVALID') from None

    def run(self, storage, job, mask_conditioning_views=None, instruction=None):
        self.last_display = None; self.last_attempt_id = None
        source, h5, obj = self.validate_inputs(storage,job)
        c = self.configuration()
        from backend.services.user_endpoint import verify_endpoint
        try:
            endpoint = verify_endpoint(job.model_dump(mode='json'))
            if endpoint and instruction is not None and instruction != job.instruction.text:
                raise ValueError('GPT2_ENDPOINT_INSTRUCTION_CHANGED')
        except ValueError: raise GuidedVLAError('GPT2_ENDPOINT_BINDING_CHANGED') from None
        s = self.settings
        attempt = s.attempts.resolve()/str(uuid4()); attempt.mkdir(parents=True,exist_ok=False)
        self.last_attempt_id = UUID(attempt.name); artifact = uuid4()
        owned = attempt/'owned'; owned.mkdir()
        if endpoint: write_json(owned/'user_end.json',endpoint)
        from backend.model_clients.gpt2_query_snapshot import snapshot_current_query
        _,target,_ = snapshot_current_query(storage,job,s.attempts,instruction=instruction,project=ROOT,stage=attempt)
        metadata=read_json(target/'metadata.json')
        write_json(attempt/'source_job.json',job.model_dump(mode='json'))
        native_code = {p.name:sha256(p) for p in s.repository.iterdir() if p.is_file() and p.suffix in ('.py','.yaml','.yml')}
        shared_code = {p.relative_to(s.shared_root).as_posix():sha256(p) for p in (s.shared_root/'vlm_project2').rglob('*.py')}
        resolved = dict(c)
        if s.retrieval_ssh_alias:
            # Backend-only transport override. Search/model/geometry policies stay native.
            resolved['server'] = dict(c['server'], ssh_alias=s.retrieval_ssh_alias)
        local_code = {}
        if s.retrieval_mode == 'local':
            # Old field names are used only by native cache identity, never SSH transport.
            resolved['server'] = dict(c['server'],ssh_alias='LOCAL_SOURCE_DIRECT',
                                     remote_root=str(s.local_retrieval_root),remote_python=str(s.python))
            local_code = {n:sha256(s.local_retrieval_root/n) for n in (
                'service/__init__.py','service/action_runtime.py','service/retrieve.py',
                'index/welding_train_v1/dinov2_base_v1/index_manifest.json',
                'index/welding_actions_v1/multilingual_e5_base_v1/index_manifest.json')}
        for k in ('data_root','api_keys_path'): resolved[k] = str((s.config.parent/c[k]).resolve())
        resolved.update(baseline_root=str(attempt/'inputs'),output_root=str(attempt/'native'/'output'),end_output_root=str(attempt/'unused-end-output'))
        resolved['max_retries'] = 0  # Explicit user single-attempt policy; native source stays read-only.
        # Current bound dataset replaces only filesystem root, not retrieval policy.
        resolved['data_root'] = str(Path(source['dataset_root']).resolve())
        (attempt/'native_config.yaml').write_text(yaml.safe_dump(resolved,allow_unicode=True),encoding='utf-8')
        native_root = attempt/'native'/'output__prediction-only'
        if (c['rough_points'],c['output_points']) != (9,33):
            native_root = native_root.with_name(native_root.name+f"__{c['rough_points']}-to-{c['output_points']}")
        mask_path = storage.artifact_path('masks',job.mask.id)
        manifest = dict(schema_version=1,backend='gpt2',source='vlm_final_gpt2',provider='gpt',
            artifact_id=str(artifact),attempt_id=attempt.name,sample_id=job.scene.sample_id,split=job.scene.split,
            workflow_job_id=str(job.id),workflow_conditioning_sha256=conditioning_hash(job),
            source_job=str(attempt/'source_job.json'),source_job_sha256=sha256(attempt/'source_job.json'),
            source_mask=str(mask_path),source_mask_sha256=sha256(mask_path),source_mask_id=str(job.mask.id),
            approved_at=job.mask.approved_at.isoformat() if job.mask.approved_at else None,
            mask_views=[],web_masks_used_as_input=False,trajectory3_used_as_input=False,
            reference_in_request=True,references_supplied_by_adapter=False,
            known_start_xyz_mm=metadata['start_xyz'],known_start_source='current query metadata.start_xyz verified against exact H5 first XYZ',
            start_h5_key='trajectory[0,:3]',start_h5_units='mm',start_xyz_order=['X','Y','Z'],start_applications=1,
            prediction_only=True,prediction_schema='gpt2-prediction-only-v1',query_gt_trajectory_included=False,baseline_prediction_included=False,
            model=c['model'],reasoning_effort=c['reasoning_effort'],
            repository=str(s.repository),native_code=native_code,shared_root=str(s.shared_root),shared_code=shared_code,
            native_directory=(native_root/target.name).relative_to(attempt).as_posix(),output_points=c['output_points'],
            native_mask_policy='all_available_gt_seam_annotations',retrieval_mode='native',
            h5=str(h5),h5_sha256=sha256(h5),obj=str(obj),obj_sha256=sha256(obj),
            scene_source_sha256=source['hashes'],scene_normalized_sha256=source['normalized_hashes'],
            rough_session=None,rough_source_files={},model_call_count_observed=None,
            files={p.relative_to(attempt).as_posix():sha256(p) for p in target.rglob('*') if p.is_file()})
        manifest['files']['native_config.yaml'] = sha256(attempt/'native_config.yaml')
        if endpoint:
            manifest.update(user_endpoint=endpoint,endpoint_conditioned=True,
                query_gt_endpoint_included=endpoint['source']=='dataset_gt_endpoint',query_gt_interior_included=False,
                endpoint_code={n:sha256(ROOT/n) for n in ('backend/model_clients/gpt2_endpoint_native.py','backend/services/user_endpoint.py')})
            manifest['files']['owned/user_end.json'] = sha256(owned/'user_end.json')
        manifest.update(local_retrieval_root=str(s.local_retrieval_root) if local_code else None,
                        local_retrieval_code=local_code,retrieval_transport=s.retrieval_mode,
                        local_retrieval_cache=str(s.local_retrieval_cache) if s.local_retrieval_cache else None,
                        local_retrieval_cache_sha256=sha256(s.local_retrieval_cache) if s.local_retrieval_cache else None)
        write_json(attempt/'request_manifest.json',manifest)
        write_json(attempt/'launch.json',dict(repository=str(s.repository),shared_root=str(s.shared_root),
            config_sha256=sha256(attempt/'native_config.yaml'),native_code=native_code,shared_code=shared_code,sample_id=job.scene.sample_id,
            retrieval_mode=s.retrieval_mode,local_retrieval_root=str(s.local_retrieval_root) if local_code else None,
            local_retrieval_code=local_code,local_retrieval_cache=manifest['local_retrieval_cache'],
            local_retrieval_cache_sha256=manifest['local_retrieval_cache_sha256'],
            **(dict(user_end_json=str(owned/'user_end.json'),user_end_sha256=sha256(owned/'user_end.json'),
                    endpoint_code=manifest['endpoint_code']) if endpoint else {})))
        write_json(attempt/'submission.json',dict(attempt_id=attempt.name,claimed=True,native_invocations=1))
        code = None
        try:
            code, _ = self.execute([str(s.python),'-B','-X','utf8','-u',str(ROOT/'backend/model_clients/gpt2_trajectory_entry.py'),str(attempt)],
                cwd=s.repository,timeout=s.timeout,diagnostic_path=attempt/'diagnostics.jsonl',preserve_openai_api_key=False,
                watchdog_policy=WatchdogPolicy(s.timeout,s.timeout,s.timeout))
        except subprocess.TimeoutExpired:
            raise GuidedVLAError('GPT2_PROCESS_TIMEOUT') from None
        except OSError: raise GuidedVLAError('GPT2_PROCESS_LAUNCH_FAILED') from None
        finally:
            write_json(attempt/'process_exit.json',dict(exit_code=code))
            self.last_display = self.capture_display(attempt,artifact,job)
        if code != 0:
            try:
                observed=read_json(attempt/'invocation_counts.json')
                if observed['model_stage_calls']==0 and observed['ssh_calls']>0:
                    raise GuidedVLAError('GPT2_NATIVE_RETRIEVAL_FAILED')
            except (OSError,ValueError,KeyError,TypeError): pass
            raise GuidedVLAError('GPT2_NATIVE_PROCESS_FAILED')
        try:
            native = attempt/manifest['native_directory']; meta,a = native_arrays(native,manifest)
            response = dict(artifact_id=str(artifact),sample_id=job.scene.sample_id,split=job.scene.split,
                source='vlm_final_gpt2',provider='gpt',model=read_json(native/'corners.json').get('model') or c['model'],point_count=len(a['predicted_path_xyz']),
                coordinate_frame=FRAME,units='mm',predicted_path_xyz_mm=a['predicted_path_xyz'].tolist(),
                prediction_only=True,ground_truth_path_xyz_mm=None,connections=a['connections'].tolist(),
                ade_mm=None,fde_mm=None,
                simulation_only=True,physical_robot_executable=False,is_robot_executable=False,retrieval_mode='native')
            write_json(attempt/'response.json',response)
            shutil.copyfile(native/'trajectory.npz',attempt/'trajectory.npz')  # Byte copy only.
            normalized = dict(source='vlm_final_gpt2',provider='gpt',artifact_id=str(artifact),attempt_id=attempt.name,
                sample_id=job.scene.sample_id,episode_id=job.scene.sample_id,split=job.scene.split,
                native_artifact_path=str(native),native_output_hash=sha256(native/'trajectory.npz'),
                point_count=response['point_count'],coordinate_frame=FRAME,units='mm',source_units='mm',scale_to_meters=.001,
                prediction_only=True,prediction_schema=meta['prediction_schema'],evaluation_performed=False,finite=True,xyz_modified=False,current_job_binding=str(job.id),instruction_binding=sha256(target/'metadata.json'),
                mask_binding=None,web_masks_used_as_input=False,native_mask_policy=meta['mask_policy'],
                native_mask_views=meta['available_mask_views'],scene_binding=source['hashes'],
                orientation_source='simulator_final_policy',vla_orientation=False,is_robot_executable=False)
            if endpoint:
                from backend.model_clients.gpt2_endpoint_native import endpoint_diagnostics
                normalized.update(endpoint_diagnostics(endpoint,a['start_xyz'],a['predicted_path_xyz']))
            write_json(attempt/'metadata.json',normalized); write_json(owned/'normalized.json',normalized)
            write_json(attempt/'completion.json',dict(attempt_id=attempt.name,response_validated=True,
                files={n:sha256(attempt/n) for n in ('response.json','trajectory.npz','metadata.json')},
                native_files={p.relative_to(attempt).as_posix():sha256(p) for p in (attempt/'native').rglob('*') if p.is_file()}))
            verify_completed_gpt2(attempt,manifest,job.model_dump(mode='json'))
            self.last_display = self.capture_display(attempt,artifact,job)
            self.last_display.validation_status = 'PASS'
            self.last_display.endpoint_diagnostics = endpoint_diagnostics(endpoint,a['start_xyz'],a['predicted_path_xyz']) if endpoint else None
            self.last_display.simulator_eligible = all(v=='within_segment' for v in response['connections'])
            write_json(owned/'validation.json',dict(status='PASS',xyz_modified=False,native_npz_preserved=True,
                web_mask_conditioning=False,robot_execution_enabled=False))
            storage._write_json(storage.artifact_path('native_context',artifact,'.vla.json'),json.dumps(dict(
                directory=str(attempt),attempt_id=attempt.name,job_id=str(job.id),
                files={p.relative_to(attempt).as_posix():sha256(p) for p in attempt.rglob('*') if p.is_file()})))
            return VLAResultSummary(artifact_id=artifact,attempt_id=UUID(attempt.name),sample_id=job.scene.sample_id,
                split=job.scene.split,model=c['model'],point_count=response['point_count'],coordinate_frame=FRAME,
                ade_mm=response['ade_mm'],fde_mm=response['fde_mm'],mask_views=meta['available_mask_views'],
                source='vlm_final_gpt2',provider='gpt',raw_output_ref=str(artifact),retrieval_mode='native',
                endpoint_diagnostics=endpoint_diagnostics(endpoint,a['start_xyz'],a['predicted_path_xyz']) if endpoint else None)
        except (OSError,ValueError,KeyError,TypeError): raise GuidedVLAError('GPT2_NATIVE_OUTPUT_INVALID') from None

    @staticmethod
    def capture_display(attempt, artifact, job):
        from backend.model_clients.geometry_display import finite_runs
        stages = []; manifest = read_json(attempt/'request_manifest.json'); native = attempt/manifest['native_directory']
        for name, label in (('rough','GPT2 · Rough'),('corners','GPT2 · Corners')):
            try:
                p = read_json(native/(name+'.json'))['proposal']
                runs, omitted = finite_runs(p['points'],connections=p.get('connections'))
                stages.append(dict(stage=label,runs=runs,omitted_point_count=omitted,
                    coordinate_frame='source_robot_start_relative_mm',units='mm',sample_id=job.scene.sample_id,current_overlay_allowed=True))
            except (OSError,ValueError,KeyError,TypeError): pass
        if (attempt/'response.json').is_file():
            r = read_json(attempt/'response.json'); runs, omitted = finite_runs(r['predicted_path_xyz_mm'],connections=r['connections'])
            stages.append(dict(stage='GPT · Final',runs=runs,omitted_point_count=omitted,coordinate_frame=FRAME,units='mm',
                sample_id=job.scene.sample_id,current_overlay_allowed=True))
        if not stages: return None
        selected = next((v for v in reversed(stages) if v['runs']),stages[-1])
        payload = dict(artifact_id=str(artifact),job_id=str(job.id),sample_id=job.scene.sample_id,source='vlm_final_gpt2',
            conditioning_sha256=conditioning_hash(job),coordinate_frame=selected['coordinate_frame'],units='mm',
            runs=selected['runs'],stages=stages,current_overlay_allowed=True)
        # Owned display may be refreshed after export; native files are never rewritten.
        file = attempt/'display.json'; file.write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False),encoding='utf-8')
        digest = __import__('hashlib').sha256(json.dumps(payload,sort_keys=True,allow_nan=False).encode()).hexdigest()
        diagnostics = read_json(attempt/'metadata.json') if (attempt/'metadata.json').is_file() and manifest.get('user_endpoint') else None
        if diagnostics: diagnostics = {k:diagnostics[k] for k in ('endpoint_conditioned','start_source','end_source','start_xyz_mm','end_xyz_mm','end_binding_hash','start_error_mm','end_error_mm','xyz_posthoc_snapped','xyz_modified_by_adapter','blind_prediction')}
        return FinalPredictionDisplay(endpoint_diagnostics=diagnostics,artifact_id=artifact,attempt_id=UUID(attempt.name),source='vlm_final_gpt2',provider='gpt',
            model=yaml.safe_load((attempt/'native_config.yaml').read_text(encoding='utf-8'))['model'],
            raw_output_ref=str(artifact),displayable=bool(selected['runs']),point_count=sum(map(len,selected['runs'])),
            omitted_point_count=selected['omitted_point_count'],coordinate_frame=selected['coordinate_frame'],units='mm',
            validation_status='UNVALIDATED',simulator_eligible=False,mask_views=[],retrieval_mode='native',
            mask_provenance={},stages=[v['stage'] for v in stages],display_ready=bool(selected['runs']),known_start_valid=True,
            coordinate_mode='absolute' if selected['coordinate_frame']==FRAME else 'relative_visualization',
            display_url=f'/api/weld/{job.id}/final-trajectory/{artifact}/display',display_sha256=digest)

    def read_display(self, storage, job, artifact):
        from backend.services.visibility_artifacts import gpt_display
        d = job.raw_final_prediction
        if not d or d.artifact_id != artifact:
            entry = next((e for e in job.previous_outputs if e['stage']=='final' and e['id']==str(artifact)),None)
            if not entry: raise GuidedVLAError('FINAL_TRAJECTORY_DISPLAY_STALE')
            d = FinalPredictionDisplay.model_validate(entry['output'])
        return dict(gpt_display(job,d,project=ROOT),artifact_id=str(artifact))

    def verify_current(self, storage, job):
        if not job.vla_prediction or job.vla_prediction.source != 'vlm_final_gpt2': raise GuidedVLAError('GPT2_ATTEMPT_INVALID')
        attempt = self.settings.attempts/str(job.vla_prediction.attempt_id)
        try: return verify_completed_gpt2(attempt,read_json(attempt/'request_manifest.json'),job.model_dump(mode='json'))
        except (OSError,ValueError,KeyError,TypeError): raise GuidedVLAError('GPT2_ATTEMPT_INVALID') from None
