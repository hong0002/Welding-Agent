"""Explicit human-only diagnostic preview. Never changes the validated fixture gate."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import numpy as np
from uuid import UUID, uuid4
from typing import Protocol
import xml.etree.ElementTree as ET

from backend.model_clients.guided_workflow import conditioning_hash
from backend.orchestrator.state_machine import WorkflowError
from backend.schemas import WorkflowState
from backend.services.simulator_prediction_package import (
    PROJECT, FRAME, PackageSettings, SimulatorPredictionAdapter, read, sha, write,
)
from backend.services.preview_mesh import load_visual_mesh

GEOMETRY = PROJECT / '.cache/bpr-geometry-audit/0efd49b0-a360-466e-b7f1-2fe5cdee0d2e/diagnostics.json'
CLEARANCE = PROJECT / '.cache/bpr-tool-clearance/a74cb77c-7d4e-4617-b20d-57a43fcb89cf/summary.json'
MODE = 'CURRENT_VLA_UNVALIDATED_PREVIEW'


class PreviewRuntime(Protocol):
    def submit(self, claim: dict) -> dict: ...
    def status(self) -> dict: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...


class WorkflowPredictionAdapter(SimulatorPredictionAdapter):
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
    def __init__(self, storage, runtime: PreviewRuntime, *, settings=None, geometry=GEOMETRY, clearance=CLEARANCE, fixtures=None):
        self.storage, self.runtime, self.settings = storage, runtime, settings
        self.geometry, self.clearance, self.fixtures = Path(geometry), Path(clearance), fixtures

    def prepare(self, *, job_id=None, artifact_id=None, kind='robot'):
        try:
            settings = self.settings or PackageSettings.from_env()
            if kind not in {'robot', 'path'}:
                raise ValueError('Unknown preview kind')
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
                # UUID-only archived live artifact action. Never select a configured sample.
                adapter = SimulatorPredictionAdapter(settings, fixtures=self.fixtures)
            package = adapter.prepare(artifact_id)
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
            evidence, clearance = read(self.geometry), read(self.clearance)
            if (package.sample_id != evidence['sample_id'] or package.sample_id != clearance['sample_id'] or
                    sha(package.h5) != evidence['h5_sha256'] or sha(package.obj) != evidence['obj_sha256'] or
                    clearance['verdict'] != 'B_PR_TOOL_CLEARANCE_FAIL' or clearance['registry_connected'] is not False):
                raise ValueError('No matching audited diagnostic placement')
            candidate = evidence['candidates'][0]
            if candidate['outward_sign'] != -1:
                raise ValueError('Existing diagnostic candidate changed')
            transform = np.asarray(candidate['source_to_scene'], dtype=float)
            rotation = transform[:3, :3]
            if (transform.shape != (4, 4) or not np.isfinite(transform).all() or
                    not np.allclose(transform[3], [0, 0, 0, 1]) or
                    not np.allclose(rotation.T @ rotation, np.eye(3)) or not np.isclose(np.linalg.det(rotation), 1)):
                raise ValueError('Diagnostic convention is not a rigid transform')
            preview_id = uuid4()
            directory = settings.project / '.cache/simulator/current-previews/packages' / str(preview_id)
            directory.mkdir(parents=True, exist_ok=False)
            descriptor = dict(schema_version='current-vla-preview-v1', preview_id=str(preview_id),
                job_id=str(job_id) if job_id else None, artifact_id=str(artifact_id), package_id=str(package.package_id),
                package=str(package.directory / 'package.json'), package_sha256=sha(package.directory / 'package.json'),
                simulator_root=str(settings.simulator_root), sample_id=package.sample_id, point_count=9,
                mode=MODE, kind=kind, fixture_ready=False, validated_simulation=False,
                physical_robot_executable=False, registry_validated=False, vla_orientation=False,
                orientation_source='simulator_fixture_policy', clearance_warning=clearance['verdict'],
                geometry=str(self.geometry), geometry_sha256=sha(self.geometry),
                clearance=str(self.clearance), clearance_sha256=sha(self.clearance),
                source_to_scene=candidate['source_to_scene'],
                object_translation_m=evidence['object_placement_candidate_only']['object_translation_m'],
                flange_rotation=candidate['fixed_tool_diagnostic']['initial_flange_rotation'],
                coordinate_frame=FRAME, ade_mm=package.ade_mm, fde_mm=package.fde_mm,
                job_conditioning_sha256=conditioning_hash(job) if job_id else None,
                job_file=str(self.storage.artifact_path('jobs', job.id, '.json')) if job_id else None,
                source_files=package.provenance['source_files'])
            descriptor['visual_geometry_preflight'] = visual_preflight
            write(directory / 'preview.json', descriptor)
            return dict(path=str(directory / 'preview.json'), sha256=sha(directory / 'preview.json'))
        except WorkflowError:
            raise
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise WorkflowError('Current VLA preview admission failed: artifact, approval or diagnostic scene changed.', 409) from None

    def run(self, *, job_id=None, artifact_id=None, kind='robot'):
        claim = self.prepare(job_id=job_id, artifact_id=artifact_id, kind=kind)
        return self.runtime.submit(claim)
