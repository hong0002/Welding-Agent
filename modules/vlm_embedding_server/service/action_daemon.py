#!/usr/bin/env python3
"""Shared GPU worker. All CUDA/FAISS work stays on one thread; no HTTP exposure."""
from __future__ import annotations

import fcntl
import json
import os
import socket
import socketserver
import struct
import time
import traceback

from service.action_rpc import ADDRESS, MAX_BYTES, ROOT, SERVICE_ID


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        _, uid, _ = struct.unpack('3i', self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != os.getuid():
            return
        self.request.settimeout(300)
        response = {'service_id': SERVICE_ID, 'pid': os.getpid()}
        try:
            line = self.rfile.readline(MAX_BYTES + 1)
            if not line or len(line) > MAX_BYTES:
                raise ValueError('Empty or oversized request')
            message = json.loads(line)
            operation = message.get('op')
            if operation == 'search':
                begin = time.perf_counter()
                result = self.server.runtime.search(message['payload'])
                elapsed = time.perf_counter() - begin
                self.server.search_count += 1
                response.update(result)
                response['resident'] = {'pid': os.getpid(), 'search_count': self.server.search_count,
                                        'search_seconds': elapsed, 'models_loaded_once': True}
                print(f"[SEARCH] sample={result['query_sample_id']} seconds={elapsed:.3f} count={self.server.search_count}", flush=True)
            elif operation == 'health':
                response.update(status='ready', search_count=self.server.search_count,
                                startup_seconds=self.server.startup_seconds,
                                gpu_indexes=self.server.runtime.gpu_index.cache_info().currsize)
            elif operation == 'stop':
                response['status'] = 'stopping'
                self.server.running = False
            else:
                raise ValueError('Unknown operation')
        except Exception as exc:
            traceback.print_exc()
            response.update(error=str(exc), error_type=type(exc).__name__)
        try:
            self.wfile.write(json.dumps(response, ensure_ascii=False, allow_nan=False).encode()+b'\n')
        except (BrokenPipeError, ConnectionResetError):
            pass  # Client disconnect must not discard the loaded models.


def main():
    with (ROOT / 'service/action_resident_instance.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        begin = time.perf_counter()
        print(f'[START] pid={os.getpid()} loading models and GPU indexes', flush=True)
        from service import action_runtime
        action_runtime.warmup()
        with socketserver.UnixStreamServer(ADDRESS, Handler) as server:
            server.runtime = action_runtime
            server.running = True
            server.search_count = 0
            server.startup_seconds = time.perf_counter() - begin
            print(f'[READY] pid={os.getpid()} startup={server.startup_seconds:.3f}s', flush=True)
            while server.running:
                server.handle_request()
        print('[STOPPED]', flush=True)


if __name__ == '__main__':
    main()
