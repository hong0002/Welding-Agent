"""Optional dataset-v2 capture evidence. No Isaac imports or motion generation."""
from pathlib import Path
import shutil
import tempfile
import time


CAPTURE_NAMES = ('P0', 'P4', 'P8', 'path_detail')


class CaptureDiagnostics:
    def __init__(self, output, event, *, clock=time.monotonic, timeout=20, staging_factory=None):
        self.output, self.event = Path(output), event
        self.clock, self.timeout = clock, timeout
        self.staging_factory = staging_factory or (lambda: tempfile.mkdtemp(prefix='weld_preview_'))
        self.staging = None
        self.attempts = []

    def attempt(self, name, *, request_capture, update):
        if name not in CAPTURE_NAMES or any(x['name']==name for x in self.attempts):
            raise ValueError('Invalid/duplicate diagnostic capture')
        entry = dict(name=name, status='FAILED', reason_code=None)
        self.attempts.append(entry)

        def warning(code, exc=None):
            entry['reason_code'] = code
            if exc is not None:
                entry['exception_class'] = type(exc).__name__
            self.event('CAPTURE_WARNING', **entry)

        try:
            if self.staging is None:
                # Non-ASCII default temp paths are refused, never handed to Kit.
                if not str(Path(tempfile.gettempdir()).resolve()).isascii():
                    warning('CAPTURE_ASCII_PATH_UNAVAILABLE')
                    return
                self.staging = Path(self.staging_factory()).resolve()
            if not str(self.staging).isascii():
                warning('CAPTURE_ASCII_PATH_UNAVAILABLE')
                return
            path = self.staging/(name+'.png')
        except OSError as exc:
            warning('CAPTURE_FILE_WRITE_FAILED', exc)
            return
        # App/scene updates are core execution; failures here must remain fatal.
        for _ in range(40):
            update()
        self.event('capture_attempted', name=name, ascii_path=True)
        try:
            request_capture(str(path))
        except Exception as exc:
            # Only the viewport API boundary is optional. Never log payload/path.
            warning('CAPTURE_API_FAILED', exc)
            return
        deadline = self.clock()+self.timeout
        while self.clock() < deadline:
            update()
            try:
                if path.is_file() and path.stat().st_size > 1000:
                    shutil.copyfile(path, self.output/(name+'.png'))
                    entry.update(status='SUCCEEDED', reason_code=None)
                    self.event('capture_written', file=name+'.png')
                    return
            except OSError as exc:
                warning('CAPTURE_FILE_WRITE_FAILED', exc)
                return
        try:
            code = ('CAPTURE_FILE_MISSING_TIMEOUT' if not path.is_file() else
                    'CAPTURE_ZERO_BYTE' if path.stat().st_size==0 else 'CAPTURE_FILE_INCOMPLETE')
        except OSError:
            code = 'CAPTURE_FILE_WRITE_FAILED'
        warning(code)

    def summary(self):
        successes = [x['name']+'.png' for x in self.attempts if x['status']=='SUCCEEDED']
        failures = [dict(x) for x in self.attempts if x['status']=='FAILED']
        return dict(capture_status='FAILED' if not successes else 'PARTIAL_FAILED' if failures else 'SUCCEEDED',
                    captures=successes, capture_diagnostics=[dict(x) for x in self.attempts],
                    capture_warning_codes=sorted({x['reason_code'] for x in failures}))


def play_waypoints(count, apply_waypoint, capture_waypoint):
    """Apply the original sequence; capture policy has no access to XYZ/joints."""
    for index in range(count):
        apply_waypoint(index)  # Scene/robot/FK exceptions propagate unchanged.
        capture_waypoint(index)
