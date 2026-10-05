#!/usr/bin/env python3
"""Lightweight SSH bridge to a shared local Unix-socket search worker (stdlib only)."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SERVICE_ID = 'welding-action-resident-v1'
# Linux abstract socket avoids the 108-byte filesystem socket path limit.
ADDRESS = '\0welding-action-' + str(os.getuid()) + '-' + hashlib.sha256(str(ROOT).encode()).hexdigest()[:20]
MAX_BYTES = 8 * 1024 * 1024


def exchange(request, timeout=300):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(ADDRESS)
        connection.sendall(json.dumps(request, ensure_ascii=False, allow_nan=False).encode() + b'\n')
        with connection.makefile('rb') as stream:
            data = stream.readline(MAX_BYTES + 1)
        if not data or len(data) > MAX_BYTES:
            raise RuntimeError('Empty or oversized resident-service reply')
    result = json.loads(data)
    if result.get('service_id') != SERVICE_ID:
        raise RuntimeError('Unexpected resident service identity')
    return result


def ensure_started(timeout):
    try:
        return exchange({'op': 'health'}, timeout)
    except (ConnectionRefusedError, FileNotFoundError):
        pass
    deadline = time.monotonic() + timeout
    lock_path = ROOT / 'service/action_resident_start.lock'
    with lock_path.open('a') as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Timed out waiting for shared service startup')
                time.sleep(.2)
        try:
            return exchange({'op': 'health'}, max(1, deadline-time.monotonic()))
        except (ConnectionRefusedError, FileNotFoundError):
            pass
        log = ROOT / 'logs/action_resident.log'
        log.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env['PYTHONPATH'] = str(ROOT) + ':' + str(ROOT / 'incoming/code')
        env['PYTHONUNBUFFERED'] = '1'
        with log.open('ab') as stream:
            process = subprocess.Popen([sys.executable, '-m', 'service.action_daemon'], cwd=ROOT,
                env=env, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                start_new_session=True, close_fds=True)
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f'Resident startup failed (exit={process.returncode}); see {log}')
            try:
                return exchange({'op': 'health'}, max(1, deadline-time.monotonic()))
            except (ConnectionRefusedError, FileNotFoundError):
                time.sleep(.25)
        raise TimeoutError(f'Resident startup still pending; see {log}; do not start duplicate workers')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--timeout', type=float, default=300)
    args = parser.parse_args()
    if args.status or args.stop:
        result = exchange({'op': 'stop' if args.stop else 'health'}, args.timeout)
    else:
        payload = json.load(sys.stdin)
        ensure_started(args.timeout)
        result = exchange({'op': 'search', 'payload': payload}, args.timeout)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 1 if result.get('error') else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps({'error': str(exc), 'type': type(exc).__name__}, ensure_ascii=False))
        sys.exit(1)
