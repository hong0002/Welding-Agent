"""Versioned current-artifact adapter; legacy replay and its registry are untouched."""
import json
import os
from pathlib import Path
import subprocess
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from backend.model_clients.guided_workflow import conditioning_hash
from backend.model_clients.native import NATIVE_PYTHON
from backend.orchestrator.state_machine import WorkflowError
from backend.services.current_preview_config import CurrentPreviewError
from backend.services.current_vla_preview import CurrentVLAPreviewService, MODE
from backend.services.environment import backend_env_values
from backend.services.legacy_prediction_adapter import metadata_for
from backend.services.simulator_prediction_package import (PROJECT, FRAME, SimulatorPredictionPackage, sha, read, write)
from backend.services.simulator2_contract import identity, exact_assets, NATIVE_FILES, Simulator2ContractError


class SimulatorPlaybackTrajectory(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    source_artifact_id: str
    source_point_count: int = Field(default=9, ge=2, le=4096)
    playback_point_count: int = Field(ge=9)
    interpolation_method: Literal['simulator2.densify_poses: Cartesian linear + orientation SLERP'] = 'simulator2.densify_poses: Cartesian linear + orientation SLERP'
    derived: Literal[True] = True
    coordinate_frame: Literal['simulator2_scene'] = 'simulator2_scene'
    units: Literal['mm'] = 'mm'


class DatasetV2Package(SimulatorPredictionPackage):
    schema_version: Literal['simulator2-current-package-v1'] = 'simulator2-current-package-v1'
    orientation_policy: Literal['simulator2_native_fixture_policy'] = 'simulator2_native_fixture_policy'
    orientation_source: Literal['simulator2_policy'] = 'simulator2_policy'
    playback: SimulatorPlaybackTrajectory


class NativeDatasetBuilder:
    """Fixed audited non-Isaac Python, shell=False, no retry; injected in offline tests."""
    def __init__(self, python=NATIVE_PYTHON):
        self.python = Path(python)
    helper = 'backend/simulator2_prepare.py'
    code_prefix = 'SIMULATOR2'
    native_options = {}

    def build(self, *, root, h5, obj, sample_id, output, prediction=None, kind='path'):
        env = {k:v for k,v in os.environ.items() if not any(w in k.upper() for w in ('TOKEN','API_KEY','SECRET'))}
        env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
        options = dict(root=str(root), h5=str(h5), obj=str(obj), sample_id=sample_id,
                       output=str(output), prediction=str(prediction) if prediction else None, kind=kind)
        options.update(self.native_options)
        try:
            process = subprocess.run([str(self.python), '-B', '-X', 'utf8', str(PROJECT/self.helper)],
                input=json.dumps(options), cwd=PROJECT, env=env, shell=False, capture_output=True,
                text=True, encoding='utf-8', timeout=180, creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            result = json.loads(process.stdout) if process.returncode == 0 else {}
        except (OSError, ValueError, subprocess.SubprocessError):
            result = {}
        if result.get('ok') is not True:
            code = result.get('code', self.code_prefix+'_SCENE_BUILD_FAIL')
            if code not in {self.code_prefix+'_'+suffix for suffix in ('SAMPLE_UNSUPPORTED','FRAME_MISMATCH','SCENE_BUILD_FAIL','IK_FAIL','PLAYBACK_FAIL')}:
                code = self.code_prefix+'_SCENE_BUILD_FAIL'
            raise CurrentPreviewError(code, 'Dataset simulator offline native preflight failed; no fallback or retry.', 409)
        return result


def backend_selection(env_file=None):
    values = backend_env_values(env_file)
    backend = os.getenv('WELD_SIM_BACKEND') or values.get('WELD_SIM_BACKEND') or 'legacy'
    if backend not in {'legacy', 'dataset_v2', 'dataset_stp','dataset_final'}:
        raise CurrentPreviewError('CURRENT_PREVIEW_CONFIGURATION_INVALID', 'WELD_SIM_BACKEND must be legacy, dataset_v2, dataset_stp or dataset_final.')
    key, default = (('WELD_SIM_FINAL_ROOT','simulator_final') if backend=='dataset_final' else
        ('WELD_SIM_STP_ROOT', 'simulator_stp') if backend == 'dataset_stp' else ('WELD_SIM2_ROOT', 'simulator2'))
    root = Path(os.getenv(key) or values.get(key) or PROJECT.parent/default).resolve()
    return backend, root


class DatasetSimulatorV2Client(CurrentVLAPreviewService):
    backend = 'dataset_v2'
    code_prefix = 'SIMULATOR2'
    native_files = NATIVE_FILES
    cache_namespace = 'simulator2'
    orientation_source = 'simulator2_policy'
    package_type = DatasetV2Package
    playback_type = SimulatorPlaybackTrajectory
    descriptor_schema = 'current-vla-preview-v3'

    def _code(self, suffix): return self.code_prefix+'_'+suffix

    def _owned_code(self):
        from backend.services.simulator2_gate import OWNED_CODE
        return OWNED_CODE

    def _validate_native(self, native, arrays, kind):
        pass

    def _descriptor_extra(self): return {}
    def __init__(self, storage, runtime, *, root=None, builder=None, **kwargs):
        super().__init__(storage, runtime, **kwargs)
        self.root = Path(root or backend_selection()[1]).resolve()
        self.builder = builder or NativeDatasetBuilder()

    def _resolve(self, job_id, artifact_id):
        if job_id is not None:
            from dataclasses import replace
            from backend.services.current_vla_preview import WorkflowPredictionAdapter
            from backend.services.simulator_prediction_package import PackageSettings
            job=self.storage.get_job(UUID(str(job_id)))
            raw=job.raw_final_prediction
            use_raw=raw and (artifact_id is not None and UUID(str(artifact_id))==raw.artifact_id or artifact_id is None and not job.vla_prediction)
            if use_raw and not (job.vla_prediction and job.vla_prediction.artifact_id==raw.artifact_id):
                settings=self.settings or PackageSettings.from_env()
                namespace='gpt2-trajectory' if raw.source=='vlm_final_gpt2' else 'gpt-trajectory'
                settings=replace(settings,attempts=settings.project/'.cache/native-models'/namespace,inputs=None)
                adapter=WorkflowPredictionAdapter(settings,self.storage,job,visualization_source=True)
                return settings,job,job.id,raw.artifact_id,adapter
        return super()._resolve(job_id,artifact_id)

    def _inputs(self, job_id, artifact_id):
        settings, job, job_id, artifact_id, adapter = self._resolve(job_id, artifact_id)
        if not job:
            raise CurrentPreviewError('CURRENT_PREVIEW_ARTIFACT_INVALID', 'Dataset v2 requires a current Workflow-bound artifact.', 409)
        selected=job.raw_final_prediction if adapter.visualization_source else job.vla_prediction
        if selected.coordinate_frame!=FRAME:
            raise CurrentPreviewError(self._code('FRAME_MISMATCH'),'Current VLA frame is not the native source robot frame.',409)
        try:
            source = adapter._source(artifact_id)
        except ValueError as exc:
            if str(exc)=='COORDINATE_FRAME_CONTRACT_MISMATCH':
                raise CurrentPreviewError(self._code('FRAME_MISMATCH'),'Current VLA frame differs from the native source convention.',409) from None
            raise
        trajectory = source[1]
        if trajectory.coordinate_frame != FRAME:
            raise CurrentPreviewError(self._code('FRAME_MISMATCH'),'Current VLA frame is not the native source robot frame.',409)
        try:
            family, _ = identity(trajectory.sample_id)
            h5, obj = exact_assets(settings.dataset_root, trajectory.sample_id)
        except Simulator2ContractError as exc:
            raise CurrentPreviewError(exc.code.replace('SIMULATOR2',self.code_prefix),str(exc),409) from None
        return settings, job, artifact_id, adapter, source, family, h5, obj

    def capabilities(self, *, job_id):
        result = dict(backend=self.backend, simulator_version=self.backend, sample_id=None, family=None,
            point_count=None, source_point_count=None, playback_point_count=None, path_preview_ready=False,
            workpiece_preview_ready=False, robot_preview_ready=False, robot_preflight_available=False,
            fixture_ready=False, simulation_only=True, physical_robot_executable=False, validated_simulation=False,
            vla_orientation=False, orientation_source=self.orientation_source, configuration_codes=[], warnings=[self._code('UNVALIDATED_SCENE')])
        try:
            settings, job, artifact, _, source, family, _, _ = self._inputs(job_id, None)
            result.update(sample_id=job.scene.sample_id, family=family, point_count=source[1].point_count, source_point_count=source[1].point_count)
            if not all((self.root/name).is_file() for name in self.native_files):
                raise CurrentPreviewError('CURRENT_PREVIEW_ASSET_MISSING', 'Dataset Simulator v2 source/assets are missing.')
            result.update(path_preview_ready=True, workpiece_preview_ready=True, robot_preflight_available=True)
            # Read only: never launch an IK/scene process on status polling.
            from backend.services.current_preview_gate import verify_preview
            for kind in ('path','robot'):
                cached = settings.project/('.cache/'+self.cache_namespace+'/readiness')/str(artifact)/(kind+'.json')
                if cached.is_file():
                    try:
                        d, _, _ = verify_preview(read(cached), project=settings.project)
                        if d['job_id']==str(job.id) and d['kind']==kind:
                            result['playback_point_count'] = d['playback_point_count']
                            if kind=='robot': result['robot_preview_ready']=True
                    except (OSError, ValueError, KeyError, TypeError):
                        pass
            if not result['robot_preview_ready']:
                result['robot_reason_code']=self._code('ROBOT_PREFLIGHT_REQUIRED')
        except CurrentPreviewError as exc:
            result['configuration_codes']=[exc.code]
        except (OSError, ValueError, KeyError, TypeError, AttributeError, WorkflowError):
            result['configuration_codes']=['CURRENT_PREVIEW_ARTIFACT_INVALID']
        return result

    def prepare(self, *, job_id=None, artifact_id=None, kind='robot'):
        try:
            if kind not in {'path','robot'}: raise ValueError('Invalid kind')
            settings, job, artifact, adapter, source, family, h5, obj = self._inputs(job_id, artifact_id)
            attempt, trajectory, manifest, hashes, data = source
            count=trajectory.point_count
            prediction_source=getattr(trajectory,'source','guided_vla')
            native_hashes = {name:sha(self.root/name) for name in self.native_files}
            # Bind every URDF visual asset as well as native source; no external writes.
            import xml.etree.ElementTree as ET
            from backend.services.preview_mesh import load_visual_mesh
            visuals=[]
            for visual in ET.parse(self.root/'rbpodo_description/robots/rb10_1300e_u.urdf').findall('./link/visual/geometry/mesh'):
                name=visual.attrib['filename'].removeprefix('package://')
                file=(self.root/name).resolve()
                if not file.is_relative_to(self.root): raise ValueError('Invalid visual path')
                native_hashes[name]=sha(file)
                if kind=='robot':
                    vertices, counts, indices=load_visual_mesh(file)
                    visuals.append(dict(file=name, vertices=len(vertices), triangles=len(counts), indices=len(indices)))
            package_id=uuid4(); directory=settings.project/'.cache/simulator/prediction-packages'/str(package_id)
            episode=directory/'predictions'/trajectory.sample_id
            episode.mkdir(parents=True, exist_ok=False)
            companion=None
            if self.backend=='dataset_final' and getattr(trajectory,'prediction_only',False):
                from backend.services.gpt2_simulator_companion import write_companion
                companion=write_companion(episode,data,h5)
            else:
                (episode/'trajectory.npz').write_bytes(data)
            write(episode/'metadata.json', metadata_for(trajectory.sample_id))
            h5_hash, obj_hash=sha(h5), sha(obj)
            native=self.builder.build(root=self.root,h5=h5,obj=obj,sample_id=trajectory.sample_id,
                output=directory/'native', prediction=episode, kind=kind)
            if (native.get('sample_id')!=trajectory.sample_id or native.get('kind')!=kind or native.get('prediction_input') is not True
                    or native['validation']['source_point_count']!=count or native.get('vla_orientation') is not False):
                raise CurrentPreviewError(self._code('PLAYBACK_FAIL'),'Native result does not bind the unchanged current prediction.',409)
            playback=self.playback_type(source_artifact_id=str(artifact), source_point_count=count,playback_point_count=native['validation']['playback_point_count'])
            provenance=dict(source_attempt=str(attempt), source_files=hashes,
                request_manifest_sha256=sha(attempt/'request_manifest.json'),
                completion_sha256=sha(attempt/'completion.json') if (attempt/'completion.json').is_file() else None,
                visualization_source=adapter.visualization_source,
                source_mask_id=manifest['source_mask_id'], approved_at=manifest['approved_at'], source_mask=manifest['source_mask'],
                source_mask_sha256=manifest['source_mask_sha256'], source_job=manifest['source_job'],source_job_sha256=manifest['source_job_sha256'],
                h5_sha256=h5_hash, obj_sha256=obj_hash, simulator_files=native_hashes, metadata_sha256=sha(episode/'metadata.json'))
            if companion is not None: provenance['prediction_companion']=companion
            # Independently check the native result, without rewriting any native array.
            import numpy as np
            from backend.simulator2_prepare import validate_playback
            with np.load(directory/'native/trajectory_solution.npz',allow_pickle=False) as arrays, np.load(episode/'trajectory.npz',allow_pickle=False) as original:
                raw=arrays['raw_tcp_pose_xyz_mm_rpy_deg']; matrix=np.asarray(native['source_to_scene'])
                if (matrix.shape!=(4,4) or not np.isfinite(matrix).all() or not np.allclose(matrix[3],[0,0,0,1])
                        or not np.allclose(matrix[:3,:3].T@matrix[:3,:3],np.eye(3)) or not np.isclose(np.linalg.det(matrix[:3,:3]),1)):
                    raise CurrentPreviewError(self._code('FRAME_MISMATCH'),'Native scene transform must be finite SE(3).',409)
                if not np.array_equal(arrays['source_to_scene'],matrix):
                    raise CurrentPreviewError(self._code('FRAME_MISMATCH'),'Native saved transform differs from its report.',409)
                world=original['predicted_path_m'].astype(float)@matrix[:3,:3].T+matrix[:3,3]
                if (raw.shape!=(count,6) or not np.allclose(raw[:,:3]*.001,world,atol=1e-9,rtol=0)
                        or not np.array_equal(arrays['predicted_source_xyz_m'],original['predicted_path_m'])
                        or not np.array_equal(arrays['ground_truth_source_xyz_m'],original['ground_truth_path_m'])):
                    raise CurrentPreviewError(self._code('PLAYBACK_FAIL'),'Native targets differ from the source prediction.',409)
                check=validate_playback(raw,arrays['tcp_pose_xyz_mm_rpy_deg'],arrays['playback_waypoint_parameter'])
                check['frame']=playback.coordinate_frame
                if check!=native['validation']: raise ValueError('Native validation differs')
                self._validate_native(native,arrays,kind)
                if kind=='robot':
                    if not {'joint_position_rad','tracking_point','cad_to_robot_tcp','urdf_tcp_to_weld_tcp'}.issubset(arrays.files):
                        raise CurrentPreviewError(self._code('IK_FAIL'),'Native robot solution is missing its IK/tool contract.',409)
                    q=arrays['joint_position_rad']
                    if (q.shape!=(playback.playback_point_count,6) or not np.isfinite(q).all()
                            or str(arrays['tracking_point'])!='mounted_fixture_v2'
                            or any(arrays[key].shape!=(4,4) or not np.isfinite(arrays[key]).all()
                                   for key in ('cad_to_robot_tcp','urdf_tcp_to_weld_tcp'))):
                        raise CurrentPreviewError(self._code('IK_FAIL'),'Native robot solution is incomplete or nonfinite.',409)
            package=self.package_type(package_id=package_id, artifact_id=artifact, attempt_id=UUID(attempt.name),
                sample_id=trajectory.sample_id, point_count=count,prediction_source=prediction_source,ade_mm=trajectory.ade_mm, fde_mm=trajectory.fde_mm, directory=directory,
                prediction_root=episode.parent,h5=h5,obj=obj,provenance=provenance, playback=playback,
                preflight=dict(fixture_ready=False, live_called=False, native=native, robot_ready=kind=='robot'))
            write(directory/'package.json', package.model_dump(mode='json'))
            preview_id=uuid4(); target=settings.project/'.cache/simulator/current-previews/packages'/str(preview_id)
            target.mkdir(parents=True, exist_ok=False)
            descriptor=dict(schema_version=self.descriptor_schema, backend=self.backend, simulator_version=self.backend,
                preview_id=str(preview_id), job_id=str(job.id), artifact_id=str(artifact), package_id=str(package_id),
                package=str(directory/'package.json'),package_sha256=sha(directory/'package.json'), simulator_root=str(self.root),
                dataset_root=str(settings.dataset_root),sample_id=trajectory.sample_id, family=family,point_count=count,source_point_count=count,
                prediction_source=prediction_source,visualization_source=adapter.visualization_source,
                playback_point_count=playback.playback_point_count, playback=playback.model_dump(mode='json'),kind=kind,mode=MODE,
                fixture_ready=False,validated_simulation=False,physical_robot_executable=False,simulation_only=True,
                registry_validated=False,vla_orientation=False,orientation_source=self.orientation_source,clearance_warning=self._code('UNVALIDATED_SCENE'),
                coordinate_frame=FRAME,source_to_scene=native['source_to_scene'],ade_mm=trajectory.ade_mm,fde_mm=trajectory.fde_mm,
                job_file=str(self.storage.artifact_path('jobs',job.id,'.json')),job_conditioning_sha256=conditioning_hash(job),
                native_files={name:sha(directory/'native'/name) for name in ('trajectory_solution.npz','report.json')},
                owned_code={name:sha(PROJECT/name) for name in self._owned_code()},visual_geometry_preflight=visuals,
                **self._descriptor_extra())
            write(target/'preview.json',descriptor)
            claim=dict(path=str(target/'preview.json'),sha256=sha(target/'preview.json'))
            from backend.services.current_preview_gate import verify_preview
            # Revalidate current source AND all assets after native math, before accepting readiness.
            adapter._source(artifact)
            verify_preview(claim,project=settings.project)
            cache=settings.project/('.cache/'+self.cache_namespace+'/readiness')/str(artifact)
            cache.mkdir(parents=True,exist_ok=True)
            from backend.services.storage import LocalStorage
            LocalStorage._write_json(cache/(kind+'.json'),json.dumps(claim))
            return claim
        except CurrentPreviewError: raise
        except FileNotFoundError:
            raise CurrentPreviewError('CURRENT_PREVIEW_ASSET_MISSING','Dataset v2 runtime source/assets are missing.') from None
        except (OSError, ValueError, KeyError, TypeError, AttributeError, WorkflowError):
            raise CurrentPreviewError('CURRENT_PREVIEW_ARTIFACT_INVALID','Current artifact or dataset-v2 package is invalid.',409) from None

    def run(self, *, job_id=None, artifact_id=None, kind='robot', selected_source=None):
        try:
            settings, _, artifact, _, source, *_ = self._inputs(job_id,artifact_id)
            if selected_source is not None:
                import io
                import numpy as np
                from backend.services.prediction_path_evidence import verify_selection
                with np.load(io.BytesIO(source[4]),allow_pickle=False) as data:
                    try: selection=verify_selection(selected_source,data['predicted_path_m'])
                    except ValueError:
                        raise CurrentPreviewError('CURRENT_PREVIEW_SELECTED_SOURCE_MISMATCH',
                            '선택한 XYZ와 native prediction package가 다릅니다. 원본 viewer에서 선택 결과를 확인하세요.',409) from None
        except CurrentPreviewError: raise
        except (WorkflowError,OSError,ValueError,KeyError,TypeError,AttributeError):
            raise CurrentPreviewError('CURRENT_PREVIEW_ARTIFACT_INVALID','Current job or immutable VLA artifact changed.',409) from None
        if hasattr(self.runtime,'check_configuration'): self.runtime.check_configuration(kind=kind)
        cached=settings.project/('.cache/'+self.cache_namespace+'/readiness')/str(artifact)/(kind+'.json')
        if cached.is_file():
            from backend.services.current_preview_gate import verify_preview
            claim=read(cached)
            try: verify_preview(claim,project=settings.project)
            except (ValueError,OSError,KeyError,TypeError):
                # Reuse the audited descriptor-only migration. Native/source XYZ,
                # existing IK/FK solution and sample assets remain untouched.
                from backend.refresh_preview_ux import refresh
                try:claim=refresh(artifact,backend=self.backend,kind=kind,project=settings.project,job_id=job_id)
                except (ValueError,OSError,KeyError,TypeError):
                    raise CurrentPreviewError('CURRENT_PREVIEW_ARTIFACT_INVALID','Cached native preflight changed. Run explicit offline preflight again.',409) from None
        else:
            claim=self.prepare(job_id=job_id,artifact_id=artifact_id,kind=kind)
        if selected_source is not None:
            # A new immutable selection descriptor; cached source/IK files are untouched.
            from copy import deepcopy
            from backend.services.current_preview_gate import verify_preview
            d, _, file=verify_preview(claim,project=settings.project)
            with np.load(file,allow_pickle=False) as data:
                if verify_selection(selected_source,data['predicted_path_m'])!=selection:
                    raise CurrentPreviewError('CURRENT_PREVIEW_SELECTED_SOURCE_MISMATCH','선택한 prediction이 변경됐습니다.',409)
            d=deepcopy(d);d.update(preview_id=str(uuid4()),prediction_selection=selection)
            target=settings.project/'.cache/simulator/current-previews/packages'/d['preview_id']/'preview.json'
            target.parent.mkdir(parents=True,exist_ok=False);write(target,d)
            claim=dict(path=str(target),sha256=sha(target))
            verify_preview(claim,project=settings.project)
        return self.runtime.submit(claim)
