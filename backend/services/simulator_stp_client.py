"""Exact sample OBJ + native STP-reference environment current VLA adapter."""
from pathlib import Path
from typing import Literal

import numpy as np

from backend.services.current_preview_config import CurrentPreviewError
from backend.services.current_preview_runtime import CurrentPreviewRuntime
from backend.services.simulator2_client import (DatasetSimulatorV2Client, NativeDatasetBuilder,
    SimulatorPlaybackTrajectory, DatasetV2Package)
from backend.services.simulator_stp_contract import NATIVE_FILES, AUDIT_FILES, inspect_native_contract


def require_native_contract(root, mode='stp'):
    if mode != 'stp':
        raise CurrentPreviewError('SIMULATOR_STP_MODE_INVALID','STP backend requires native --layout stp.',503)
    try:
        evidence=inspect_native_contract(root)
        if evidence['contract_pass']: return evidence
    except (OSError,ValueError,SyntaxError,TypeError):
        pass
    raise CurrentPreviewError('SIMULATOR_STP_SOURCE_INVALID','Native STP source/layout is missing or invalid.',503)


class SimulatorStpPlaybackTrajectory(SimulatorPlaybackTrajectory):
    interpolation_method: Literal['simulator_stp.densify_poses: Cartesian linear + orientation SLERP'] = 'simulator_stp.densify_poses: Cartesian linear + orientation SLERP'
    coordinate_frame: Literal['simulator_stp_scene'] = 'simulator_stp_scene'


class DatasetStpPackage(DatasetV2Package):
    schema_version: Literal['simulator-stp-current-package-v1'] = 'simulator-stp-current-package-v1'
    orientation_policy: Literal['simulator_stp_native_fixture_policy'] = 'simulator_stp_native_fixture_policy'
    orientation_source: Literal['simulator_stp_policy'] = 'simulator_stp_policy'
    playback: SimulatorStpPlaybackTrajectory


class NativeStpBuilder(NativeDatasetBuilder):
    helper='backend/simulator_stp_prepare.py'
    code_prefix='SIMULATOR_STP'
    native_options={'backend':'dataset_stp','layout':'stp'}


class DatasetStpPreviewRuntime(CurrentPreviewRuntime):
    def __init__(self, config, *, root, mode='stp', **kwargs):
        super().__init__(config,backend='dataset_stp',**kwargs)
        self.repository_root,self.mode=Path(root).resolve(),mode

    def check_configuration(self, **kwargs):
        require_native_contract(self.repository_root,self.mode)
        super().check_configuration(**kwargs)

    def status(self):
        result=super().status()
        try: require_native_contract(self.repository_root,self.mode)
        except CurrentPreviewError as exc:
            for value in (result,result['robot_configuration']):
                value['configured']=False
                value['configuration_codes'].append(exc.code)
                value['configuration_errors'].append(str(exc))
        return result


class DatasetSimulatorStpClient(DatasetSimulatorV2Client):
    backend='dataset_stp'
    code_prefix='SIMULATOR_STP'
    native_files=NATIVE_FILES
    cache_namespace='simulator-stp'
    orientation_source='simulator_stp_policy'
    package_type=DatasetStpPackage
    playback_type=SimulatorStpPlaybackTrajectory
    descriptor_schema='current-vla-preview-stp-v1'

    def __init__(self, storage, runtime, *, root, mode='stp', builder=None, **kwargs):
        self.repository_root,self.mode=Path(root).resolve(),mode
        super().__init__(storage,runtime,root=self.repository_root/'simulator',builder=builder or NativeStpBuilder(),**kwargs)

    def _inputs(self, job_id, artifact_id):
        require_native_contract(self.repository_root,self.mode)
        return super()._inputs(job_id,artifact_id)

    def _owned_code(self):
        from backend.services.simulator_stp_gate import OWNED_CODE
        return OWNED_CODE

    def _descriptor_extra(self):
        return dict(native_layout='stp',cad_source='sample_obj',environment_source='stp_reference_layout')

    def capabilities(self, *, job_id):
        result=super().capabilities(job_id=job_id)
        result.update(cad_source='OBJ',native_layout='stp_reference_layout',environment_source='stp_reference_layout')
        return result

    def _validate_native(self, native, arrays, kind):
        if (native.get('native_layout')!='stp' or native.get('native_flags')!=['--layout','stp']
                or native.get('cad_source')!='sample_obj' or native.get('orientation_source')!=self.orientation_source
                or str(arrays['environment_layout'])!='stp'):
            raise CurrentPreviewError(self._code('SCENE_BUILD_FAIL'),'Native output does not bind STP layout.',409)
        environment=native['environment']
        fields=('environment_floor_z_m','environment_table_center_xy_m','environment_table_size_xy_m','fixture_table_top_m')
        if (environment.get('layout')!='stp' or any(not np.isfinite(arrays[key]).all() for key in fields)
                or any(float(arrays[key])!=float(value) for key,value in
                    (('environment_floor_z_m',-.670),('fixture_table_top_m',-.010)))):
            raise CurrentPreviewError(self._code('SCENE_BUILD_FAIL'),'Native STP environment evidence is invalid.',409)
        if kind=='robot':
            for key in ('position_error_mm','orientation_error_deg'):
                value=arrays[key]
                if value.shape!=(native['validation']['playback_point_count'],) or not np.isfinite(value).all() or value.min()<0 or value.max()>1:
                    raise CurrentPreviewError(self._code('IK_FAIL'),'Native IK residual exceeds its diagnostic tolerance.',409)
            for key in ('fk_residual_mm_max','orientation_residual_deg_max'):
                value=native[key]
                if value is None or not np.isfinite(value) or value<0 or value>1:
                    raise CurrentPreviewError(self._code('IK_FAIL'),'Native interpolated FK residual is invalid.',409)
