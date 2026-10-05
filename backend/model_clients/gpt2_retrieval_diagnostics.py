"""Observe original native retrieval without replacing its transport or parser.

Only fixed categories and exception classes are persisted, never payloads/errors.
"""
import json
from pathlib import Path
import re
import subprocess
import sys
import time


def ssh_category(stderr, code):
    text = (stderr or '').lower()
    for phrase, category in (
        ('could not resolve hostname', 'SSH_HOSTNAME_UNRESOLVED'),
        ('permission denied (publickey)', 'SSH_AUTH_FAILED'),
        ('host key verification failed', 'SSH_HOST_KEY_REJECTED'),
        ('connection timed out', 'SSH_CONNECT_TIMEOUT'),
        ('connection refused', 'SSH_CONNECTION_REFUSED'),
        ('no such file or directory', 'REMOTE_PATH_MISSING'),
        ('no module named', 'REMOTE_MODULE_MISSING'),
    ):
        if phrase in text:
            return category
    return 'SSH_NONZERO_EXIT' if code else 'SSH_TRANSPORT_COMPLETED'


class RetrievalDiagnostics:
    def __init__(self, shared_root, path, *, profile=None):
        self.client_file = str(Path(shared_root) / 'vlm_project2/retrieval_client.py')
        self.fewshot_file = str(Path(shared_root) / 'vlm_project2/fewshot_examples.py')
        self.path = Path(path)
        self.profile = profile
        self.started = time.monotonic()
        self.report = dict(ssh_calls=0, timeout=False, remote_command_stage='NOT_RUN',
                           response_parse_stage='NOT_RUN', failure_stage=None,
                           native_cache_used=False, local_examples_prepared=False)

    def observe(self, frame, event, arg):
        if self.profile:
            self.profile(frame, event, arg)
        name, filename = frame.f_code.co_name, frame.f_code.co_filename
        if filename == self.fewshot_file and name == 'prepare_examples' and event == 'return' and isinstance(arg, tuple):
            self.report['local_examples_prepared'] = True
            self.report['native_cache_used'] = self.report['ssh_calls'] == 0
        if filename == self.client_file and name == 'retrieve_actions':
            if event == 'call':
                self.report['remote_command_stage'] = 'REQUEST_STARTED'
            elif event == 'return' and isinstance(arg, dict):
                self.report['remote_command_stage'] = 'RESPONSE_RECEIVED'
        if name != 'run' or frame.f_globals.get('__name__') != 'subprocess':
            return
        args = frame.f_locals.get('popenargs', ())
        if not (args and isinstance(args[0], list) and args[0] and Path(args[0][0]).name.lower() in ('ssh', 'ssh.exe')):
            return
        if event == 'call':
            self.report['ssh_calls'] += 1
            print('[GPT2_RETRIEVAL] ssh_started', flush=True)
        elif event == 'return' and isinstance(arg, subprocess.CompletedProcess):
            self.report['subprocess_exit_code'] = arg.returncode
            category = ssh_category(arg.stderr, arg.returncode)
            self.report['ssh_stderr_category'] = category
            result = None
            for line in reversed((arg.stdout or '').splitlines()):
                try:
                    result = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
            self.report['response_parse_stage'] = 'JSON_OBJECT' if isinstance(result, dict) else 'INVALID_RESPONSE'
            if isinstance(result, dict) and result.get('error'):
                error_type = str(result.get('type', ''))
                allowed = {'RuntimeError','TimeoutError','FileNotFoundError','ModuleNotFoundError','ImportError',
                           'ValueError','TypeError','KeyError','OSError','PermissionError','BlockingIOError',
                           'ConnectionRefusedError','ConnectionResetError','JSONDecodeError'}
                self.report['remote_exception_class'] = error_type if error_type in allowed else 'UNSPECIFIED'
                self.report['remote_command_stage'] = 'ERROR_RESPONSE'
                self.report['failure_stage'] = 'REMOTE_SERVICE'
                # Match only the native RPC's fixed startup messages; never save detail.
                message = str(result['error'])
                startup = re.match(r'Resident startup failed \(exit=(-?\d{1,5})\);', message)
                if startup:
                    self.report['remote_reason_code'] = 'NATIVE_RESIDENT_STARTUP_FAILED'
                    self.report['resident_exit_code'] = int(startup[1])
                elif message.startswith('Timed out waiting for shared service startup'):
                    self.report['remote_reason_code'] = 'NATIVE_RESIDENT_START_LOCK_TIMEOUT'
                elif message.startswith('Resident startup still pending;'):
                    self.report['remote_reason_code'] = 'NATIVE_RESIDENT_STARTUP_PENDING'
            elif arg.returncode:
                self.report['failure_stage'] = (
                    'SSH_CONFIG' if category == 'SSH_HOSTNAME_UNRESOLVED' else
                    'SSH_CONNECT' if category.startswith('SSH_') else
                    'REMOTE_PYTHON' if category == 'REMOTE_MODULE_MISSING' else 'REMOTE_COMMAND')
            elif not isinstance(result, dict):
                self.report['failure_stage'] = 'RESPONSE_PARSE'
            else:
                self.report['remote_command_stage'] = 'RESPONSE_RECEIVED'

    def trace(self, frame, event, arg):
        if frame.f_code.co_filename not in (self.client_file, self.fewshot_file):
            return None
        if event == 'exception':
            exc = arg[1]
            if frame.f_code.co_filename == self.client_file and isinstance(exc, json.JSONDecodeError):
                return self.trace  # Native reverse-line parser deliberately catches these.
            # No stringification of exception values, args, stdout, stderr or locals.
            if not isinstance(exc, (StopIteration, GeneratorExit)):
                self.report['exception_class'] = type(exc).__name__
                if isinstance(exc, subprocess.TimeoutExpired):
                    # A supervisor deadline alone cannot distinguish connect/service delay.
                    self.report.update(timeout=True, failure_stage='UNKNOWN', remote_command_stage='TIMEOUT')
                elif frame.f_code.co_filename == self.fewshot_file and not self.report['failure_stage']:
                    self.report['failure_stage'] = 'LOCAL_ASSET_RESOLUTION'
        return self.trace

    def __enter__(self):
        self.old_profile, self.old_trace = sys.getprofile(), sys.gettrace()
        sys.setprofile(self.observe)
        sys.settrace(self.trace)
        return self

    def __exit__(self, *exc):
        sys.setprofile(self.old_profile)
        sys.settrace(self.old_trace)
        self.report['elapsed_seconds'] = round(time.monotonic() - self.started, 3)
        self.path.write_text(json.dumps(self.report, indent=2), encoding='utf-8')
