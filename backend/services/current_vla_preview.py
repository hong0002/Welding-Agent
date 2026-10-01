"""Explicit human-only diagnostic preview. Never changes the validated fixture gate."""
from __future__ import annotations

from dataclasses import replace
import json
import io
from pathlib import Path
import numpy as np
from uuid import UUID, uuid4
from typing import Protocol, Literal
import xml.etree.ElementTree as ET

from backend.model_clients.guided_workflow import conditioning_hash
from backend.orchestrator.state_machine import WorkflowError
from backend.schemas import WorkflowState
from backend.services.simulator_prediction_package import (
    PROJECT, FRAME, PackageSettings, SimulatorPredictionAdapter, SimulatorPredictionPackage, read, sha, write,
)
from backend.services.legacy_prediction_adapter import metadata_for
from backend.services.preview_mesh import load_visual_mesh
from backend.services.current_preview_config import GEOMETRY, CLEARANCE, CurrentPreviewError
from backend.services.preview_policy import default_registry

MODE = 'CURRENT_VLA_UNVALIDATED_PREVIEW'


class PreviewRuntime(Protocol):
    def submit(self, claim: dict) -> dict: ...
    def status(self) -> dict: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...


class PathPredictionPackage(SimulatorPredictionPackage):
    """Neutral diagnostic package has no applied tool/fixture orientation."""
    schema_version: Literal['current-vla-path-package-v1'] = 'current-vla-path-package-v1'
    orientation_policy: Literal['none_xyz_only'] = 'none_xyz_only'
    orientation_source: Literal['simulator_preview_policy; not VLA'] = 'simulator_preview_policy; not VLA'


class DiagnosticPredictionAdapter(SimulatorPredictionAdapter):
    """Path-only package never consults legacy fixture readiness or launches its probe."""
    def preview_source(self, artifact_id, policy, kind):
        source = self._source(artifact_id)
        with np.load(io.BytesIO(source[4]), allow_pickle=False) as arrays:
            assets = policy.validate_sample_assets(self.settings.dataset_root, source[1].sample_id,
                                                  arrays['ground_truth_path_m'])
        placement = policy.derive_or_resolve_source_to_scene(assets, kind)
        transform = np.asarray(placement['source_to_scene'], dtype=float)
        if (transform.shape != (4,4) or not np.isfinite(transform).all() or
                not np.allclose(transform[3], [0,0,0,1]) or
                not np.allclose(transform[:3,:3].T@transform[:3,:3], np.eye(3)) or
                not np.isclose(np.linalg.det(transform[:3,:3]), 1)):
            raise CurrentPreviewError('PREVIEW_POLICY_NOT_READY', 'Preview policy requires a finite rigid display transform.', 409)
        return source, assets, placement

    def prepare_preview(self, artifact_id, policy, kind):
        (attempt, trajectory, manifest, hashes, data), assets, placement = self.preview_source(artifact_id, policy, kind)
        if kind == 'robot':
            package = super().prepare(artifact_id)
            if package.provenance['h5_sha256'] != assets.h5_sha256 or package.provenance['obj_sha256'] != assets.obj_sha256:
                raise CurrentPreviewError('PREVIEW_H5_MISMATCH', 'Query assets changed during admission.', 409)
            return package, assets, placement
        outputs = self._owned(self.settings.outputs, self.settings.project / '.cache')
        if outputs.is_relative_to(attempt) or outputs.is_relative_to(self.settings.simulator_root.resolve()):
            raise ValueError('Preview package output must be separate backend cache')
        package_id = uuid4()
        directory = outputs / str(package_id)
        episode = directory / 'predictions' / trajectory.sample_id
        episode.mkdir(parents=True, exist_ok=False)
        with (episode/'trajectory.npz').open('xb') as stream:
            stream.write(data)
        write(episode/'metadata.json', metadata_for(trajectory.sample_id))
        provenance = dict(source_attempt=str(attempt), source_files=hashes,
            request_manifest_sha256=sha(attempt/'request_manifest.json'), completion_sha256=sha(attempt/'completion.json'),
            source_mask_id=manifest['source_mask_id'], approved_at=manifest['approved_at'],
            source_mask=manifest['source_mask'], source_mask_sha256=manifest['source_mask_sha256'],
            source_job=manifest['source_job'], source_job_sha256=manifest['source_job_sha256'],
            h5_sha256=assets.h5_sha256, obj_sha256=assets.obj_sha256, simulator_files={},
            metadata_sha256=sha(episode/'metadata.json'), frame_evidence='Direct H5 XYZ mm-to-meter/index-linear GT check; no prediction alignment.')
        package = PathPredictionPackage(package_id=package_id, artifact_id=artifact_id, attempt_id=UUID(attempt.name),
            sample_id=trajectory.sample_id, ade_mm=trajectory.ade_mm, fde_mm=trajectory.fde_mm, directory=directory,
            prediction_root=episode.parent, h5=assets.h5, obj=assets.obj, provenance=provenance,
            preflight=dict(verdict='CURRENT_VLA_PATH_PREVIEW_OFFLINE_READY', current_preview_only=True,
                package_contract='PASS', fixture_ready=False, gt_h5_frame_error_mm_max=assets.gt_h5_error_mm_max,
                n9_supported=True, fixture={'sample_id':trajectory.sample_id, 'ready':False}, live_called=False))
        write(directory/'package.json', package.model_dump(mode='json'))
        return package, assets, placement

    def verify(self, package):
        if not package.preflight.get('current_preview_only'):
            return super().verify(package)
        attempt, trajectory, _, hashes, _ = self._source(package.artifact_id)
        if (package.sample_id != trajectory.sample_id or package.attempt_id != UUID(attempt.name) or
                package.provenance['source_files'] != hashes or sha(attempt/'request_manifest.json') != package.provenance['request_manifest_sha256'] or
                sha(attempt/'completion.json') != package.provenance['completion_sha256'] or
                sha(package.h5) != package.provenance['h5_sha256'] or sha(package.obj) != package.provenance['obj_sha256'] or
                sha(package.prediction_root/package.sample_id/'trajectory.npz') != hashes['trajectory.npz'] or
                sha(package.prediction_root/package.sample_id/'metadata.json') != package.provenance['metadata_sha256']):
            raise ValueError('Current path package changed')


class WorkflowPredictionAdapter(DiagnosticPredictionAdapter):
    """Extend the existing immutable export for current Workflow-owned attempts."""
    def __init__(self, settings, storage, job, **kwargs):
        super().__init__(settings, **kwargs)
        self.storage, self.job_id = storage, job.id

    def _attempt(self, artifact_id):
        job = self.storage.get_job(self.job_id)
        if job.state != WorkflowState.VLA_READY or not job.vla_prediction or job.vla_prediction.artifact_id != artifact_id:
            raise ValueError('Current job no longer identifies this VLA result')
        proof = read(self.storage.artifact_path('native_context', artifact_id, '.vla.json'))
        attempt = self._owned(proof['directory'], self.settings.project / '.cache')
        if proof['job_id'] != str(job.id) or proof['attempt_id'] != str(job.vla_prediction.attempt_id) or attempt.name != proof['attempt_id']:
            raise ValueError('Wrong current-job artifact binding')
        if any(sha(attempt / name) != digest for name, digest in proof['files'].items()):
            raise ValueError('Current VLA proof changed')
        return attempt

    def _source(self, artifact_id):
        attempt = self._attempt(artifact_id)
        manifest = read(attempt / 'request_manifest.json')
        job = self.storage.get_job(self.job_id)
        if (manifest.get('workflow_job_id') != str(job.id) or
                conditioning_hash(job) != manifest.get('workflow_conditioning_sha256') or
                manifest.get('source_mask_id') != str(job.mask.id) or
                manifest.get('approved_at') != job.mask.approved_at.isoformat() or
                manifest.get('mask_views') != ['F']):
            raise ValueError('Current conditioning/approval differs')
        scene = read(self.storage.artifact_path('native_context', job.id, '.scene.json'))
        if any(sha(scene['images'][v]) != h for v, h in manifest['scene_source_sha256'].items()):
            raise ValueError('Source images changed')
        if any(sha(self.storage.artifact_path('scenes', job.scene.views[v].image_id)) != h
               for v, h in manifest['scene_normalized_sha256'].items()):
            raise ValueError('Canvas images changed')
        if any(sha(Path(manifest['rough_session']) / name) != h for name, h in manifest['rough_source_files'].items()):
            raise ValueError('Native guidance changed')
        # The CLI export verifier already checks response, NPZ, input snapshots,
        # approval and episode identity. Workflow manifests have a dataset hash
        # instead of the older CLI inputs-file hash.
        resolved = super()._source(artifact_id)
        trajectory = resolved[1]
        if (trajectory.sample_id != job.scene.sample_id or trajectory.split != job.scene.split or
                trajectory.sample_id != job.vla_prediction.sample_id or
                trajectory.coordinate_frame != job.vla_prediction.coordinate_frame):
            raise ValueError('Current scene and trajectory differ')
        return resolved


class CurrentVLAPreviewService:
    def __init__(self, storage, runtime: PreviewRuntime, *, settings=None, geometry=GEOMETRY, clearance=CLEARANCE, fixtures=None, registry=None):
        self.storage, self.runtime, self.settings = storage, runtime, settings
        self.geometry, self.clearance, self.fixtures = Path(geometry), Path(clearance), fixtures
        self.registry = registry or default_registry(self.geometry, self.clearance)

    def _resolve(self, job_id, artifact_id):
        settings = self.settings or PackageSettings.from_env()
        job = None
        if job_id is None and artifact_id is not None:
            proof_path = self.storage.artifact_path('native_context', UUID(str(artifact_id)), '.vla.json')
            if proof_path.is_file():
                job_id = UUID(read(proof_path)['job_id'])
        if job_id is not None:
            job = self.storage.get_job(UUID(str(job_id)))
            if job.state != WorkflowState.VLA_READY or not job.vla_prediction:
                raise ValueError('Current job must be VLA_READY')
            if artifact_id is not None and UUID(str(artifact_id)) != job.vla_prediction.artifact_id:
                raise ValueError('Current artifact mismatch')
            artifact_id = job.vla_prediction.artifact_id
            proof = read(self.storage.artifact_path('native_context', artifact_id, '.vla.json'))
            settings = replace(settings, attempts=Path(proof['directory']).parent, inputs=None)
            adapter = WorkflowPredictionAdapter(settings, self.storage, job, fixtures=self.fixtures)
        else:
            artifact_id = UUID(str(artifact_id))
            adapter = DiagnosticPredictionAdapter(settings, fixtures=self.fixtures)
        return settings, job, job_id, artifact_id, adapter

    def capabilities(self, *, job_id):
        """Read-only UI preflight: no package, process, lease, model or queue."""
        result = dict(sample_id=None, family=None, point_count=None, path_preview_ready=False,
            robot_preview_ready=False, workpiece_preview_ready=False, fixture_ready=False,
            simulation_only=True, physical_robot_executable=False, validated_simulation=False,
            vla_orientation=False, configuration_codes=[], warnings=[])
        try:
            _, job, _, artifact_id, adapter = self._resolve(job_id, None)
            result.update(sample_id=job.scene.sample_id, point_count=job.vla_prediction.point_count)
            policy = self.registry.resolve(job.scene.sample_id)
            result['family'] = policy.family
            _, _, placement = adapter.preview_source(artifact_id, policy, 'path')
            result.update(path_preview_ready=True, workpiece_preview_ready=placement['workpiece_preview_ready'], warnings=placement['warnings'])
            try:
                adapter.preview_source(artifact_id, policy, 'robot')
                result['robot_preview_ready'] = True
            except CurrentPreviewError as exc:
                result['robot_reason_code'] = exc.code
        except CurrentPreviewError as exc:
            result['configuration_codes'] = [exc.code]
        except (WorkflowError, OSError, ValueError, KeyError, TypeError, AttributeError):
            result['configuration_codes'] = ['CURRENT_PREVIEW_ARTIFACT_INVALID']
        return result

    def prepare(self, *, job_id=None, artifact_id=None, kind='robot'):
        try:
            if kind not in {'robot', 'path'}:
                raise ValueError('Unknown preview kind')
            settings, job, job_id, artifact_id, adapter = self._resolve(job_id, artifact_id)
            # Resolve identity from immutable current artifact, never the legacy configured sample.
            trajectory = adapter._source(artifact_id)[1]
            policy = self.registry.resolve(trajectory.sample_id)
            package, assets, placement = adapter.prepare_preview(artifact_id, policy, kind)
            adapter.verify(package)
            visual_preflight = []
            if kind == 'robot':
                tree = ET.parse(settings.simulator_root / 'rbpodo_description/robots/rb10_1300e_u.urdf')
                for visual in tree.findall('./link/visual/geometry/mesh'):
                    asset = (settings.simulator_root / visual.attrib['filename'].replace('package://','')).resolve()
                    if not asset.is_relative_to(settings.simulator_root.resolve()):
                        raise ValueError('Unaudited robot visual path')
                    vertices, counts, indices = load_visual_mesh(asset)
                    visual_preflight.append(dict(file=asset.relative_to(settings.simulator_root).as_posix(),
                        sha256=sha(asset),vertices=len(vertices),triangles=len(counts),indices=len(indices)))
            preview_id = uuid4()
            directory = settings.project / '.cache/simulator/current-previews/packages' / str(preview_id)
            directory.mkdir(parents=True, exist_ok=False)
            descriptor = dict(schema_version='current-vla-preview-v2', preview_id=str(preview_id),
                job_id=str(job_id) if job_id else None, artifact_id=str(artifact_id), package_id=str(package.package_id),
                package=str(package.directory / 'package.json'), package_sha256=sha(package.directory / 'package.json'),
                simulator_root=str(settings.simulator_root), sample_id=package.sample_id, point_count=package.point_count,
                mode=MODE, kind=kind, fixture_ready=False, validated_simulation=False,
                physical_robot_executable=False, simulation_only=True, registry_validated=False, vla_orientation=False,
                orientation_source='simulator_preview_policy', clearance_warning=placement['clearance_warning'],
                policy=placement, family=policy.family, source_to_scene=placement['source_to_scene'],
                show_workpiece=placement['workpiece_preview_ready'],
                object_translation_m=(placement['workpiece_placement'] or {}).get('translation_m'),
                robot_base_placement=placement['robot_base_placement'], flange_rotation=placement['tool_orientation'],
                coordinate_frame=FRAME, ade_mm=package.ade_mm, fde_mm=package.fde_mm,
                job_conditioning_sha256=conditioning_hash(job) if job_id else None,
                job_file=str(self.storage.artifact_path('jobs', job.id, '.json')) if job_id else None,
                source_files=package.provenance['source_files'])
            descriptor['sample_assets'] = dict(h5_sha256=assets.h5_sha256, obj_sha256=assets.obj_sha256,
                h5_shape=list(assets.h5_shape), obj_bounds_mm=assets.obj_bounds_mm, gt_h5_error_mm_max=assets.gt_h5_error_mm_max)
            descriptor['owned_code'] = {name:sha(PROJECT/name) for name in ('backend/current_vla_isaac_preview.py',
                'backend/services/current_preview_gate.py', 'backend/services/preview_policy.py', 'backend/services/dataset_sample.py')}
            descriptor['visual_geometry_preflight'] = visual_preflight
            write(directory / 'preview.json', descriptor)
            return dict(path=str(directory / 'preview.json'), sha256=sha(directory / 'preview.json'))
        except CurrentPreviewError:
            raise
        except WorkflowError:
            raise CurrentPreviewError('CURRENT_PREVIEW_ARTIFACT_INVALID', 'Current job, VLA artifact or immutable prediction package is invalid.', 409) from None
        except FileNotFoundError:
            raise CurrentPreviewError('CURRENT_PREVIEW_ASSET_MISSING', 'Current Preview requires its backend dataset binding and audited assets.') from None
        except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, ET.ParseError):
            raise CurrentPreviewError('CURRENT_PREVIEW_ARTIFACT_INVALID', 'Current VLA preview admission failed: artifact, approval or diagnostic scene changed.', 409) from None

    def run(self, *, job_id=None, artifact_id=None, kind='robot'):
        # Requested mode admission precedes launcher/assets: robot-pending never auto-falls back to path.
        try:
            _, _, _, resolved_id, adapter = self._resolve(job_id, artifact_id)
            policy = self.registry.resolve(adapter._source(resolved_id)[1].sample_id)
            adapter.preview_source(resolved_id, policy, kind)
        except CurrentPreviewError:
            raise
        except (WorkflowError, OSError, ValueError, KeyError, TypeError, AttributeError):
            raise CurrentPreviewError('CURRENT_PREVIEW_ARTIFACT_INVALID', 'Current job or VLA artifact is invalid.', 409) from None
        if hasattr(self.runtime, 'check_configuration'):
            self.runtime.check_configuration(kind=kind)
        claim = self.prepare(job_id=job_id, artifact_id=artifact_id, kind=kind)
        return self.runtime.submit(claim)
