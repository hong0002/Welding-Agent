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

    def _fail(self, message):
        self.state, self.error = 'FAILED', message
        if self.latest:
            self.latest.update(status='FAILED', error=message)
            if self.backend in {'dataset_v2','dataset_stp'}:
                self.latest.update(reason_code=self._playback_code, playback_status='FAILED')
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
            if code is not None:
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
                    if self.backend in {'dataset_v2','dataset_stp'} and (data.get('backend')!=self.backend
                            or data.get('source_point_count')!=9 or data.get('playback_point_count')!=self.latest['playback_point_count']
                            or data.get('playback_derived') is not True or data.get('sample_family')!=self.latest['sample_family']):
                        self.latest['reason_code']=self._playback_code
                        self._fail(self._playback_code+': derived result differs from admitted native package.')
                        return
                    if (data.get('artifact_id') != self.latest['artifact_id'] or data.get('package_id') != self.latest['package_id'] or
                            data.get('point_count') != 9 or data.get('state') != 'done' or data.get('exact_xyz_preserved') is not True or
                            data.get('fixture_ready') is not False or data.get('physical_robot_executable') is not False):
                        self._fail('Preview result failed or differs from current admitted artifact.')
                        return
                    output = self.session / 'outputs' / self.latest['request_id']
                    evidence = ('scene.usda', 'waypoints.npz', 'report.json') if self.backend in {'dataset_v2','dataset_stp'} else ('scene.usda', 'P0.png', 'P8.png')
                    if not all((output/name).is_file() and (output/name).stat().st_size > (1000 if name!='report.json' else 0) for name in evidence):
                        self._fail('Preview completion missing scene/capture evidence.')
                        return
                    if self.backend in {'dataset_v2','dataset_stp'}:
                        from backend.services.preview_capture_result import validate_result
                        try:
                            summary = validate_result(data, output, self.latest, descriptor)
                        except (ValueError, OSError, KeyError, TypeError):
                            self._fail(self._playback_code+': incomplete playback evidence.')
                            return
                        self.latest.update(**summary)
                    self.latest.update(status='SUCCEEDED', robot_motion=data['robot_motion'], exact_xyz_preserved=True)
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

    def stop(self):
        with self.lock:
            if self.latest and self.latest['status'] == 'QUEUED':
                self.latest.update(status='CANCELLED')
            try:
                self._release()
            except Exception:
                self._fail('Owned current preview cleanup failed; lease retained.')
                raise WorkflowError(self.error, 503) from None
            self.state, self.error = 'STOPPED', None

    def close(self):
        self.wake.set(); self.stop()
        if self.thread:
            self.thread.join(timeout=2)
