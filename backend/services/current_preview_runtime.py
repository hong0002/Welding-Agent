"""Owned GUI preview process, sharing the existing runtime lease. No sample launcher."""
from collections import deque
import json
from pathlib import Path
import threading
import time
from uuid import uuid4

from backend.orchestrator.state_machine import WorkflowError
from backend.services.current_preview_gate import verify_preview
from backend.services.simulator_client import SimulatorConfig, timestamp
from backend.services.simulator_process import FileLease, ProcessLauncher
from backend.services.storage import LocalStorage
from backend.services.current_preview_config import (configuration, require_configuration,
    GEOMETRY, CLEARANCE, CurrentPreviewError)


class CurrentPreviewRuntime:
    def __init__(self, config=None, *, launcher=None, clock=time.monotonic, monitor=True, geometry=GEOMETRY, clearance=CLEARANCE, backend='legacy'):
        self.config = config or SimulatorConfig.from_env()
        self.backend = backend
        self.geometry, self.clearance = Path(geometry), Path(clearance)
        self.launcher = launcher or ProcessLauncher()
        self.clock, self.monitor = clock, monitor
        self.lock = threading.RLock()
        self.process = self.lease = self.session = self.latest = None
        self.state, self.error = 'STOPPED', None
        self.entries = deque(maxlen=150)
        self.started = self.submitted = 0.
        self.ready_seen = False
        self.wake = threading.Event()
        self.thread = None
        self.sequence = 0

    @property
    def _playback_code(self):
        return ('SIMULATOR_STP' if self.backend=='dataset_stp' else 'SIMULATOR2')+'_PLAYBACK_FAIL'

    def _log(self, line):
        self.sequence += 1
        self.entries.append(dict(id=self.sequence, at=timestamp(), source='current-preview', text=line[:1000]))

    def _read(self, process):
        try:
            for line in process.stdout:
                # Fixed high-level runner messages only; no arbitrary Kit payloads.
                if not line.startswith('[CURRENT_PREVIEW] '):
                    continue
                with self.lock:
                    if process is not self.process:
                        continue
                    line = line.strip()
                    self._log(line)
                    with (self.session / 'native.log').open('a', encoding='utf-8') as log:
                        log.write(line+'\n')
                    if line == '[CURRENT_PREVIEW] READY ' + self.session.name:
                        self.ready_seen = True
        finally:
            process.stdout.close()

    def submit(self, claim):
        with self.lock:
            self.tick()
            if self.state not in {'STOPPED', 'READY', 'FAILED'} or (self.state == 'FAILED' and self.process):
                raise WorkflowError('Current preview is busy; no retry or parallel launch.', 409)
            try:
                d, _, _ = verify_preview(claim)
            except (OSError, ValueError, KeyError, TypeError):
                raise CurrentPreviewError('CURRENT_PREVIEW_ARTIFACT_INVALID', 'Current Preview package or source evidence changed.', 409) from None
            if d.get('backend',self.backend) != self.backend:
                raise CurrentPreviewError('CURRENT_PREVIEW_ARTIFACT_INVALID','Preview backend differs from configured runtime.',409)
            self.check_configuration(kind=d['kind'])
            if self.process and (d.get('robot_demo_only') or (self.latest or {}).get('robot_demo_only')):
                raise WorkflowError('다음 미리보기를 열기 전에 현재 Demo 창을 중지하세요.',409)
            if self.process and bool((self.latest or {}).get('geometry_only'))!=bool(d.get('geometry_only')):
                raise WorkflowError('표시 모드를 바꾸기 전에 현재 시뮬레이터를 중지하세요.',409)
            if Path(d['simulator_root']).resolve() != self.config.root.resolve():
                raise WorkflowError('Preview simulator assets differ from launcher configuration.', 409)
            new_process = self.process is None
            if new_process:
                try:
                    self.lease = FileLease(self.config.runtime_dir / 'owner.lock')
                except RuntimeError as exc:
                    raise WorkflowError(str(exc), 409) from None
                except OSError:
                    raise WorkflowError('Cannot acquire current preview runtime ownership.', 503) from None
            try:
                if new_process:
                    self.session = self.config.runtime_dir / 'current-previews/sessions' / str(uuid4())
                    (self.session / 'queue').mkdir(parents=True)
                    (self.session / 'results').mkdir()
                    LocalStorage._write_json(self.session / 'catalog.json', '{}')
                    self.ready_seen = False
                catalog = json.loads((self.session / 'catalog.json').read_text(encoding='utf-8'))
                catalog[d['artifact_id']] = claim
                LocalStorage._write_json(self.session / 'catalog.json', json.dumps(catalog))
                request = uuid4()
                command = dict(type='preview_current_vla', artifact_id=d['artifact_id'], mode='unvalidated', kind=d['kind'])
                self.latest = {key:d[key] for key in ('job_id', 'artifact_id', 'package_id', 'sample_id', 'point_count',
                    'mode', 'kind', 'fixture_ready', 'physical_robot_executable', 'validated_simulation', 'clearance_warning',
                    'orientation_source', 'vla_orientation', 'coordinate_frame', 'ade_mm', 'fde_mm')}
                self.latest.update(request_id=str(request), status='QUEUED', robot_motion=False, error=None)
                self.latest['prediction_selection']=d.get('prediction_selection')
                self.latest['scene_mode']=d.get('scene_mode') or ('CURRENT_SAMPLE_STP' if self.backend=='dataset_stp' and not d.get('geometry_only') and not d.get('robot_demo_only') else None)
                self.latest['geometry_only']=bool(d.get('geometry_only'))
                self.latest['robot_demo_only']=bool(d.get('robot_demo_only'))
                self.latest['demo_transformed']=bool(d.get('demo_transformed'))
                self.latest.update(backend=self.backend, simulator_version=self.backend,
                    session_id=self.session.name,
                    sample_family=d.get('family'),source_point_count=d['point_count'],
                    playback_point_count=d.get('playback_point_count'))
                if self.backend in {'dataset_v2','dataset_stp'}:
                    self.latest.update(playback_status='PENDING', capture_status='PENDING', capture_warning_codes=[])
                self.claim = claim
                LocalStorage._write_json(self.session / 'queue' / (str(request)+'.json'), json.dumps(command))
                self.submitted = self.clock()
                if new_process:
                    self.started = self.clock()
                    self.state, self.error = 'STARTING', None
                    self.process = self.launcher.preview(self.config.executable, self.config.root,
                        dict(session=str(self.session), first_request=str(request)))
                    threading.Thread(target=self._read, args=(self.process,), daemon=True).start()
                    if self.monitor and self.thread is None:
                        self.thread = threading.Thread(target=self._monitor, daemon=True); self.thread.start()
                else:
                    self.state = 'RUNNING_PREVIEW'
            except Exception:
                self._fail('Preview launcher failed; no retry was attempted.')
                if self.backend in {'dataset_v2','dataset_stp'}:
                    raise CurrentPreviewError(self._playback_code,self.error,503) from None
                raise WorkflowError(self.error, 503) from None
            return self.status()

    def _release(self):
        if self.process:
            self.process.stop(); self.process = None
        if self.lease:
            self.lease.close(); self.lease = None

    def _fail(self, message, *, reason_code=None, stage=None):
        self.state, self.error = 'FAILED', message
        if self.latest:
            self.latest.update(status='FAILED', error=message)
            if self.backend in {'dataset_v2','dataset_stp'}:
                self.latest.update(reason_code=reason_code or self._playback_code, playback_status='FAILED')
            if reason_code:
                self.latest['reason_code'] = reason_code
            if stage:
                self.latest['failure_stage'] = stage
        self._log(message)
        try:
            self._release()
        except Exception:
            self.error += ' Owned process cleanup incomplete; lease retained.'

    def tick(self):
        with self.lock:
            try:
                self._tick()
            except Exception:
                self._fail('Current preview artifact/monitor check failed; owned process cancelled.')

    def _tick(self):
        with self.lock:
            if not self.process:
                return
            code = self.process.poll()
            # A pre-GUI failure can finish before READY or before stdout drains.
            # Read the owned, request-bound safe result before the generic exit.
            result = self.session / 'results' / (self.latest['request_id']+'.json')
            if result.is_file():
                from backend.services.preview_startup import public_failure
                failure = public_failure(json.loads(result.read_text(encoding='utf-8')),
                                         self.latest['request_id'], self.session.name)
                if failure:
                    if code is not None:
                        self.latest['exit_code'] = code
                    self._fail(failure['error'], reason_code=failure['reason_code'], stage=failure['stage'])
                    return
            if code is not None:
                self.latest['exit_code'] = code
                self._fail(f'Preview process exited (exit={code}); see sanitized native log.')
                return
            if self.state == 'STARTING':
                if self.ready_seen:
                    self.state = 'RUNNING_PREVIEW'
                elif self.clock()-self.started > self.config.startup_timeout:
                    self._fail('Current preview readiness timeout. Owned process cancelled.')
            if self.state == 'RUNNING_PREVIEW':
                result = self.session / 'results' / (self.latest['request_id']+'.json')
                if result.is_file():
                    descriptor, _, _ = verify_preview(self.claim)  # Reject an upstream edit even after display.
                    data = json.loads(result.read_text(encoding='utf-8'))
                    if data.get('state') == 'failed':
                        if self.backend in {'dataset_v2','dataset_stp'}:
                            self.latest['reason_code']=self._playback_code
                        self._fail('Current preview failed during '+str(data.get('phase','renderer'))[:40]+
                                   ' ('+str(data.get('exception_class','Error'))[:40]+'). No retry was attempted.')
                        return
                    geometry_only=self.latest.get('geometry_only',False)
                    demo=self.latest.get('robot_demo_only',False)
                    if not geometry_only and not demo and self.backend in {'dataset_v2','dataset_stp'} and (data.get('backend')!=self.backend
                            or data.get('source_point_count')!=self.latest['source_point_count'] or data.get('playback_point_count')!=self.latest['playback_point_count']
                            or data.get('playback_derived') is not True or data.get('sample_family')!=self.latest['sample_family']):
                        self.latest['reason_code']=self._playback_code
                        self._fail(self._playback_code+': derived result differs from admitted native package.')
                        return
                    if (data.get('artifact_id') != self.latest['artifact_id'] or data.get('package_id') != self.latest['package_id'] or
                            data.get('point_count') != self.latest['point_count'] or data.get('state') != 'done' or data.get('exact_xyz_preserved') is not True or
                            data.get('fixture_ready') is not False or data.get('physical_robot_executable') is not False):
                        self._fail('Preview result failed or differs from current admitted artifact.')
                        return
                    output = self.session / 'outputs' / self.latest['request_id']
                    evidence = ('scene.usda','geometry.json','waypoints.npz','report.json') if demo else ('scene.usda','geometry.json','report.json') if geometry_only else ('scene.usda', 'waypoints.npz', 'report.json') if self.backend in {'dataset_v2','dataset_stp'} else ('scene.usda', 'P0.png', 'P8.png')
                    if not all((output/name).is_file() and (output/name).stat().st_size > (0 if geometry_only or demo or name=='report.json' else 1000) for name in evidence):
                        self._fail('Preview completion missing scene/capture evidence.')
                        return
                    if demo:
                        from backend.services.current_preview_gate import read
                        import numpy as np
                        with np.load(output/'waypoints.npz',allow_pickle=False) as recorded:
                            with np.load(Path(descriptor['package']).parent/'demo_playback.npz',allow_pickle=False) as prepared:
                                exact_demo=np.array_equal(recorded['demo_playback_points'],prepared['demo_playback_points']) and np.array_equal(recorded['joint_position_rad'],prepared['joint_position_rad'])
                            motion=recorded['joint_position_rad'].shape==(descriptor['playback_point_count'],6) and np.max(np.abs(np.diff(recorded['joint_position_rad'],axis=0)))>1e-7
                            if descriptor.get('prediction_selection'):
                                from backend.services.prediction_path_evidence import verify_demo_source
                                proof=verify_demo_source(read(Path(descriptor['package'])),recorded,read(Path(descriptor['package']).parent/'demo_mapping.json'))
                                if (any(data.get(k)!=v for k,v in proof.items()) or data.get('prediction_selection')!=descriptor['prediction_selection']
                                        or descriptor['prediction_selection']['source_xyz_sha256']!=proof['source_xyz_sha256']):
                                    self._fail('ROBOT_DEMO_SOURCE_MISMATCH');return
                                if not np.allclose(recorded['rendered_path_world_m'],recorded['demo_playback_points'],atol=2e-7,rtol=0):
                                    self._fail('ROBOT_DEMO_RED_PATH_MISMATCH');return
                                self.latest.update(**proof,renderer_source_point_count=data['renderer_source_point_count'])
                        if (read(output/'geometry.json')!=read(Path(descriptor['package'])) or not exact_demo or not motion
                                or data.get('robot_demo_only') is not True or data.get('rb10_joints_moved') is not True
                                or data.get('physical_execution') is not False or data.get('physics_stepping') is not False):
                            self._fail('ROBOT_DEMO_EVIDENCE_INVALID');return
                        self.latest.update(playback_status='SUCCEEDED',capture_status=data.get('capture_status','FAILED'),source_preserved=True,rb10_joints_moved=True)
                    elif geometry_only:
                        from backend.services.geometry_preview import read
                        if (read(output/'geometry.json')!=read(Path(descriptor['package']))
                                or data.get('robot_motion') is not False or data.get('physics_stepping') is not False):
                            self._fail('Geometry evidence differs from source.');return
                        self.latest.update(playback_status='NOT_REQUESTED',capture_status=data.get('capture_status','FAILED'))
                    elif self.backend in {'dataset_v2','dataset_stp'}:
                        from backend.services.preview_capture_result import validate_result
                        try:
                            summary = validate_result(data, output, self.latest, descriptor)
                        except (ValueError, OSError, KeyError, TypeError):
                            self._fail(self._playback_code+': incomplete playback evidence.')
                            return
                        self.latest.update(**summary)
                    self.latest.update(status='SUCCEEDED', robot_motion=data['robot_motion'], exact_xyz_preserved=True,
                        scene_composition=data.get('scene_composition'))
                    self.state = 'READY'
                elif self.clock()-self.submitted > self.config.sample_timeout:
                    self._fail('Current preview timeout. Owned process cancelled.')

    def _monitor(self):
        while not self.wake.wait(.25):
            try:
                self.tick()
            except Exception:
                with self.lock:
                    self._fail('Current preview monitor failure; owned process cancelled.')

    def status(self):
        self.tick()
        with self.lock:
            return dict(**configuration(self.config, kind='path'), robot_configuration=configuration(self.config, kind='robot'),
                        backend=self.backend, simulator_version=self.backend,
                        sample_family=(self.latest or {}).get('sample_family'),
                        source_point_count=(self.latest or {}).get('source_point_count'),
                        playback_point_count=(self.latest or {}).get('playback_point_count'),
                        state=self.state, error=self.error, latest=self.latest,
                        can_stop=self.process is not None, pid=self.process.pid if self.process else None)

    def check_configuration(self, *, geometry=None, clearance=None, kind='robot'):
        require_configuration(self.config, kind=kind)

    def preview_frames(self, job_id, artifact_id):
        from backend.services.current_preview_frames import list_frames
        with self.lock:
            self.tick()
            return list_frames(self, job_id, artifact_id, verify_preview)

    def preview_frame(self, job_id, artifact_id, session_id, request_id, name, digest):
        from backend.services.current_preview_frames import frame_bytes
        with self.lock:
            self.tick()
            return frame_bytes(self, job_id, artifact_id, session_id, request_id, name, digest, verify_preview)

    def live_packet(self, job_id, artifact_id, session_id, request_id):
        from backend.services.current_preview_live import read_packet
        with self.lock:
            self.tick()
            return read_packet(self, job_id, artifact_id, session_id, request_id, verify_preview)

    def stop(self):
        with self.lock:
            if self.latest and self.latest['status'] == 'QUEUED':
                self.latest.update(status='CANCELLED')
            try:
                if self.session and self.process:
                    LocalStorage._write_json(self.session / 'stop.json', '{}')
                self._release()
            except Exception:
                self._fail('Owned current preview cleanup failed; lease retained.')
                raise WorkflowError(self.error, 503) from None
            self.state, self.error = 'STOPPED', None

    def close(self):
        self.wake.set(); self.stop()
        if self.thread:
            self.thread.join(timeout=2)
