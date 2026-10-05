"""Thin native final adapter; shared immutable source gates and process ownership."""
import json
import os
from pathlib import Path
from typing import Literal
import numpy as np
from backend.services.simulator_final_result import validate as validate_final_result,observed_completion

from backend.services.simulator2_client import DatasetSimulatorV2Client,NativeDatasetBuilder,SimulatorPlaybackTrajectory
from backend.services.simulator_stp_client import DatasetSimulatorStpClient,DatasetStpPackage
from backend.services.current_preview_config import CurrentPreviewError
from backend.services.current_preview_runtime import CurrentPreviewRuntime
from backend.services.simulator_final_contract import NATIVE_FILES,require_native_contract


class FinalPlayback(SimulatorPlaybackTrajectory):
    interpolation_method:Literal['simulator_final.densify_poses: Cartesian linear + orientation SLERP']='simulator_final.densify_poses: Cartesian linear + orientation SLERP'
    coordinate_frame:Literal['simulator_final_scene']='simulator_final_scene'


class FinalPackage(DatasetStpPackage):
    schema_version:Literal['simulator-final-current-package-v1']='simulator-final-current-package-v1'
    orientation_policy:Literal['simulator_final_native_fixture_policy']='simulator_final_native_fixture_policy'
    orientation_source:Literal['simulator_final_policy']='simulator_final_policy'
    playback:FinalPlayback


class NativeFinalBuilder(NativeDatasetBuilder):
    helper='backend/simulator_final_prepare.py'
    code_prefix='SIMULATOR_FINAL'
    native_options={'backend':'dataset_final','layout':'stp'}


class SimulatorFinalClient(DatasetSimulatorStpClient):
    backend='dataset_final'
    code_prefix='SIMULATOR_FINAL'
    native_files=NATIVE_FILES
    cache_namespace='simulator-final'
    orientation_source='simulator_final_policy'
    package_type=FinalPackage
    playback_type=FinalPlayback
    descriptor_schema='current-vla-preview-final-v1'

    def __init__(self,storage,runtime,*,root,builder=None,**kwargs):
        self.repository_root=Path(root).resolve()
        DatasetSimulatorV2Client.__init__(self,storage,runtime,root=self.repository_root,builder=builder or NativeFinalBuilder(),**kwargs)

    def _inputs(self,*args):
        require_native_contract(self.root)
        return DatasetSimulatorV2Client._inputs(self,*args)

    def _owned_code(self):
        from backend.services.simulator_final_gate import OWNED_CODE
        return OWNED_CODE

    def capabilities(self,*,job_id):
        result=DatasetSimulatorV2Client.capabilities(self,job_id=job_id)
        result.update(path_preview_ready=False,path_viewer='WEB_SOURCE_FRAME',native_layout='stp_reference_layout',cad_source='OBJ')
        return result

    def prepare(self,*,kind='robot',**kwargs):
        if kind!='robot':
            raise CurrentPreviewError('SIMULATOR_FINAL_ROBOT_PREVIEW_REQUIRED','Native final renderer previews the path and robot together. Use the web XYZ viewer for path-only inspection.',409)
        return super().prepare(kind=kind,**kwargs)

    def run_demo(self,*,preview,job,selected_source):
        """Relative/raw selection is explicitly DEMO; native absolute remains STRICT."""
        if preview.scene_preview is not self or preview.runtime is not self.runtime:
            raise CurrentPreviewError('CURRENT_PREVIEW_SELECTED_SOURCE_MISMATCH','현재 preview source binding을 확인하세요.',409)
        return preview._run_demo(job,selected_source)


class SimulatorFinalRuntime(CurrentPreviewRuntime):
    def __init__(self,config,**kwargs):super().__init__(config,backend='dataset_final',**kwargs)

    @property
    def _playback_code(self):return 'SIMULATOR_FINAL_PLAYBACK_FAIL'

    def check_configuration(self,**kwargs):
        require_native_contract(self.config.root)
        return super().check_configuration(**kwargs)

    def submit(self,claim):
        with self.lock:
            if self.process:
                raise CurrentPreviewError('SIMULATOR_FINAL_STOP_REQUIRED','현재 native preview를 중지한 뒤 다음 preview를 시작하세요.',409)
            self.playback_finished_seen=self.scene_saved_seen=self.native_traceback_seen=False
            status=super().submit(claim)
            self.latest.update(playback_status='PENDING',capture_status='PENDING',capture_warning_codes=[],
                scene_mode='CURRENT_SAMPLE_STP' if self.latest.get('robot_demo_only') else 'NATIVE_FINAL')
            return status

    def _read(self,process):
        secrets=[v for k,v in os.environ.items() if any(w in k.upper() for w in ('TOKEN','API_KEY','SECRET')) and len(v)>6]
        try:
            for line in process.stdout:
                for secret in secrets:line=line.replace(secret,'[REDACTED]')
                with self.lock:
                    if process is not self.process:continue
                    with (self.session/'sanitized.native.log').open('a',encoding='utf-8') as log:log.write(line)
                    self.observe_native_line(line.strip())
                    if line.startswith('[CURRENT_PREVIEW] '):
                        self._log(line.strip())
                        if line.strip()=='[CURRENT_PREVIEW] READY '+self.session.name:self.ready_seen=True
        finally:process.stdout.close()

    def observe_native_line(self,line):
        if line=='[PLAYBACK] finished':self.playback_finished_seen=True
        if line=='[SAVE] '+str(self.session/'outputs'/self.latest['request_id']/'scene.usda'):
            self.scene_saved_seen=True
        if line.startswith('Traceback (most recent call last):'):self.native_traceback_seen=True

    def _tick(self):
        if self.latest and self.latest.get('robot_demo_only'):
            return super()._tick()
        if not self.process:return
        code=self.process.poll()
        result=self.session/'results'/(self.latest['request_id']+'.json')
        if result.is_file():
            from backend.services.preview_startup import public_failure
            failure=public_failure(json.loads(result.read_text(encoding='utf-8')),self.latest['request_id'],self.session.name)
            if failure:
                self._fail(failure['error'],reason_code=failure['reason_code'],stage=failure['stage'])
                return
        if code is not None:
            self.latest['exit_code']=code
            self._fail(f'Native final preview exited (exit={code}); check the sanitized native log.',reason_code='SIMULATOR_FINAL_PLAYBACK_FAIL')
            return
        if self.state=='STARTING':
            if self.ready_seen:self.state='RUNNING_PREVIEW'
            elif self.clock()-self.started>self.config.startup_timeout:
                self._fail('Native final readiness timeout.',reason_code='SIMULATOR_FINAL_PLAYBACK_FAIL')
        if self.state=='RUNNING_PREVIEW':
            result=self.session/'results'/(self.latest['request_id']+'.json')
            if not result.is_file() and self.playback_finished_seen and self.scene_saved_seen:
                from backend.services.current_preview_gate import verify_preview
                from backend.services.storage import LocalStorage
                try:
                    if self.native_traceback_seen:raise ValueError('Native traceback observed')
                    descriptor,_,_=verify_preview(self.claim)
                    output=self.session/'outputs'/self.latest['request_id']
                    data=observed_completion(descriptor,self.latest,output,
                        playback_finished=self.playback_finished_seen,scene_saved=self.scene_saved_seen)
                    LocalStorage._write_json(output/'report.json',json.dumps(data))
                    LocalStorage._write_json(result,json.dumps(data))
                    self._log('[CURRENT_PREVIEW] NATIVE_PLAYBACK_COMPLETE')
                except (OSError,ValueError,KeyError,TypeError):
                    self._fail('Native playback completion evidence is invalid.',reason_code='SIMULATOR_FINAL_OUTPUT_INVALID')
                    return
            if result.is_file():
                from backend.services.current_preview_gate import verify_preview
                descriptor,_,_=verify_preview(self.claim)
                output=self.session/'outputs'/self.latest['request_id']
                data=json.loads(result.read_text(encoding='utf-8'))
                validate_final_result(data,output,self.latest,descriptor)
                self.latest.update(status='SUCCEEDED',playback_status='SUCCEEDED',capture_status='SUCCEEDED',
                    capture_warning_codes=[],robot_motion=True,exact_xyz_preserved=True,
                    path_source_is_current_prediction=True,renderer_source_point_count=descriptor['source_point_count'])
                self.state='READY'
            elif self.clock()-self.submitted>self.config.sample_timeout:
                self._fail('Native final playback timeout.',reason_code='SIMULATOR_FINAL_PLAYBACK_FAIL')
