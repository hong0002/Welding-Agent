"""Diagnostic family policies + exact query assets. No inference or Isaac imports."""
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
import io
import h5py
import numpy as np

from backend.services.dataset_sample import resolve_sample, exact_assets
from backend.services.legacy_prediction_adapter import MAX_FRAME_ERROR_MM
from backend.services.simulator_prediction_package import read, sha
from backend.services.current_preview_config import CurrentPreviewError, GEOMETRY, CLEARANCE


def rejected(code, message):
    raise CurrentPreviewError(code, message, 409)


@dataclass(frozen=True)
class SampleAssets:
    sample_id: str
    family: str
    h5: Path
    obj: Path
    h5_sha256: str
    obj_sha256: str
    h5_shape: tuple
    obj_bounds_mm: list
    gt_h5_error_mm_max: float


class PreviewPolicy(Protocol):
    family: str
    supports_path_preview: bool
    supports_robot_preview: bool
    def resolve_h5(self, root: Path, sample_id: str) -> Path: ...
    def resolve_obj(self, root: Path, sample_id: str) -> Path: ...
    def validate_sample_assets(self, root: Path, sample_id: str, gt: np.ndarray) -> SampleAssets: ...
    def derive_or_resolve_source_to_scene(self, assets: SampleAssets, kind: str) -> dict: ...


@dataclass(frozen=True)
class SourceFramePreviewPolicy:
    family: str
    supports_path_preview: bool = True
    supports_robot_preview: bool = False

    def _identity(self, sample_id):
        if resolve_sample(sample_id).family != self.family:
            rejected('PREVIEW_H5_MISMATCH', 'Query sample does not belong to this preview policy.')

    def resolve_h5(self, root, sample_id):
        self._identity(sample_id)
        return exact_assets(root, sample_id)[0]

    def resolve_obj(self, root, sample_id):
        self._identity(sample_id)
        return exact_assets(root, sample_id)[1]

    def validate_sample_assets(self, root, sample_id, gt):
        h5, obj = self.resolve_h5(root, sample_id).resolve(), self.resolve_obj(root, sample_id).resolve()
        # Exact directory structure AND basename: no same-family substitute/symlink.
        expected = exact_assets(root, sample_id)
        if h5 != expected[0] or obj != expected[1] or not h5.is_relative_to(root.resolve()) or not obj.is_relative_to(root.resolve()):
            rejected('PREVIEW_H5_MISMATCH', 'Exact sample asset mapping changed.')
        if not h5.is_file():
            rejected('PREVIEW_SAMPLE_ASSET_MISSING', 'The current sample H5 is missing.')
        if not obj.is_file():
            rejected('PREVIEW_OBJ_MISSING', 'The current sample OBJ is missing.')
        h5_bytes, obj_bytes = h5.read_bytes(), obj.read_bytes()
        try:
            with h5py.File(io.BytesIO(h5_bytes), 'r') as handle:
                teaching = np.asarray(handle['trajectory'], dtype=float)
            if (teaching.ndim != 2 or teaching.shape[1] not in (3, 6) or len(teaching) < 2 or
                    not np.isfinite(teaching).all() or gt.ndim != 2 or gt.shape[1] != 3 or not np.isfinite(gt).all()):
                raise ValueError()
            # Same index-linear check/tolerance as existing replay, only GT is resampled.
            expected_gt = np.column_stack([np.interp(np.linspace(0, len(teaching)-1, len(gt)),
                np.arange(len(teaching)), teaching[:, axis])*.001 for axis in range(3)])
            error = float(np.linalg.norm(gt-expected_gt, axis=1).max()*1000)
            if error > MAX_FRAME_ERROR_MM:
                raise ValueError()
        except (OSError, ValueError, KeyError):
            rejected('PREVIEW_H5_MISMATCH', 'Response GT does not match the exact query H5/frame/units.')
        try:
            lines = obj_bytes.decode('utf-8-sig').splitlines()
            vertices = np.asarray([[float(v) for v in line.split()[1:4]] for line in lines if line.startswith('v ')])
            if vertices.ndim != 2 or vertices.shape[1] != 3 or not len(vertices) or not np.isfinite(vertices).all():
                raise ValueError()
            faces = [line.split()[1:] for line in lines if line.startswith('f ')]
            if not faces or any(len(face) < 3 or any(int(token.split('/')[0]) == 0 or
                abs(int(token.split('/')[0])) > len(vertices) for token in face) for face in faces):
                raise ValueError()
        except (UnicodeError, ValueError, IndexError):
            rejected('PREVIEW_POLICY_NOT_READY', 'The current sample OBJ geometry is invalid.')
        import hashlib
        return SampleAssets(sample_id, self.family, h5, obj, hashlib.sha256(h5_bytes).hexdigest(),
            hashlib.sha256(obj_bytes).hexdigest(), teaching.shape,
            [vertices.min(0).tolist(), vertices.max(0).tolist()], error)

    def derive_or_resolve_source_to_scene(self, assets, kind):
        if kind == 'robot':
            rejected('PREVIEW_PATH_SUPPORTED_ROBOT_PENDING', 'Path Preview is supported; robot/workpiece placement policy is pending.')
        return dict(policy_id=f'{self.family}:source-frame-v1', family=self.family,
            supports_path_preview=True, supports_robot_preview=False, frame_mode='source_frame',
            source_to_scene=np.eye(4).tolist(), workpiece_placement=None, robot_base_placement=None,
            tool_orientation=None, workpiece_preview_ready=False,
            warnings=['PREVIEW_PATH_SUPPORTED_ROBOT_PENDING'], clearance_warning='NOT_AUDITED',
            provenance='Identity display of source XYZ in meters. No CAD/robot registration is asserted.', evidence_files={})


class BppPreviewPolicy(SourceFramePreviewPolicy):
    def __init__(self):
        super().__init__('B_PP')


class BprPreviewPolicy(SourceFramePreviewPolicy):
    def __init__(self, geometry=GEOMETRY, clearance=CLEARANCE):
        super().__init__('B_PR', supports_robot_preview=True)
        object.__setattr__(self, 'geometry', Path(geometry))
        object.__setattr__(self, 'clearance', Path(clearance))

    def derive_or_resolve_source_to_scene(self, assets, kind):
        # Family capability is conditional on an exact audited sample, never on the prefix alone.
        try:
            evidence, clearance = read(self.geometry), read(self.clearance)
            if assets.sample_id != evidence['sample_id']:
                if kind == 'path':
                    return super().derive_or_resolve_source_to_scene(assets, kind)
                rejected('PREVIEW_POLICY_NOT_READY', 'Robot Preview requires an exact audited sample placement.')
            if assets.h5_sha256 != evidence['h5_sha256'] or assets.obj_sha256 != evidence['obj_sha256']:
                rejected('PREVIEW_H5_MISMATCH', 'Exact audited sample assets changed.')
            if (assets.sample_id != clearance['sample_id'] or
                    clearance['verdict'] != 'B_PR_TOOL_CLEARANCE_FAIL' or clearance['registry_connected'] is not False or
                    evidence['candidates'][0]['outward_sign'] != -1):
                raise ValueError()
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            rejected('PREVIEW_POLICY_NOT_READY', 'Robot Preview requires an exact audited sample placement.')
        candidate = evidence['candidates'][0]
        transform = np.asarray(candidate['source_to_scene'], dtype=float)
        if (transform.shape != (4,4) or not np.isfinite(transform).all() or
                not np.allclose(transform[3], [0,0,0,1]) or not np.allclose(transform[:3,:3].T@transform[:3,:3], np.eye(3)) or
                not np.isclose(np.linalg.det(transform[:3,:3]), 1)):
            rejected('PREVIEW_POLICY_NOT_READY', 'Audited placement is not a rigid transform.')
        return dict(policy_id='B_PR:audited-diagnostic-v1', family=self.family,
            supports_path_preview=True, supports_robot_preview=True, frame_mode='audited_diagnostic_scene',
            source_to_scene=transform.tolist(), workpiece_preview_ready=True,
            workpiece_placement={'translation_m':evidence['object_placement_candidate_only']['object_translation_m']},
            robot_base_placement=np.eye(4).tolist(),
            tool_orientation=candidate['fixed_tool_diagnostic']['initial_flange_rotation'],
            warnings=['B_PR_TOOL_CLEARANCE_FAIL'], clearance_warning='B_PR_TOOL_CLEARANCE_FAIL',
            provenance='Existing exact H5/OBJ audited candidate only; not a validated physical fixture.',
            evidence_files={str(self.geometry):sha(self.geometry), str(self.clearance):sha(self.clearance)})


class PreviewPolicyRegistry:
    def __init__(self, policies):
        self.policies = {}
        for policy in policies:
            if policy.family in self.policies:
                raise ValueError('Duplicate preview family policy')
            self.policies[policy.family] = policy

    def resolve(self, sample_id):
        try:
            family = resolve_sample(sample_id).family
        except (ValueError, TypeError):
            rejected('PREVIEW_FAMILY_UNSUPPORTED', 'Malformed or unknown dataset sample family.')
        if family not in self.policies:
            rejected('PREVIEW_FAMILY_UNSUPPORTED', 'No diagnostic preview policy is registered for this family.')
        return self.policies[family]


def default_registry(geometry=GEOMETRY, clearance=CLEARANCE):
    # Existing replay fixture logic is left untouched. These three are path-only until separately audited.
    return PreviewPolicyRegistry([BprPreviewPolicy(geometry, clearance), BppPreviewPolicy(),
        SourceFramePreviewPolicy('L_PR'), SourceFramePreviewPolicy('T_PR'), SourceFramePreviewPolicy('T_PP')])
