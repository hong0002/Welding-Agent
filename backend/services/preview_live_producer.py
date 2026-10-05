"""Optional viewport-only frames. No desktop capture, motion or Isaac imports.

Pump from the owned Kit update loop; never wait for a capture. One in-flight
callback and one atomic latest JPEG/metadata pair keep memory/disk bounded.
"""
import ctypes
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import time

FPS = 8
SIZE = (1280, 720)
QUALITY = 80


def viewport_rgba(buffer, size, width, height):
    if not (0 < width <= 4096 and 0 < height <= 4096 and size == width * height * 4):
        raise ValueError('Unsupported viewport buffer')
    if isinstance(buffer, (bytes, bytearray, memoryview)):
        data = bytes(buffer)
    else:
        # Kit's ByteCapture delivers a PyCapsule; copy before callback returns.
        get_name = ctypes.pythonapi.PyCapsule_GetName
        get_name.restype = ctypes.c_char_p
        get_name.argtypes = (ctypes.py_object,)
        pointer = ctypes.pythonapi.PyCapsule_GetPointer
        pointer.restype = ctypes.c_void_p
        pointer.argtypes = (ctypes.py_object, ctypes.c_char_p)
        address = pointer(buffer, get_name(buffer))
        if not address:
            raise ValueError('Empty viewport buffer')
        data = ctypes.string_at(address, size)
    if len(data) != size:
        raise ValueError('Incomplete viewport buffer')
    return data


class LiveFrameProducer:
    def __init__(self, output, identity, *, clock=time.monotonic, wall=time.time, event=None):
        self.output = Path(output) / 'live'
        self.identity = dict(identity)
        self.clock, self.wall, self.event = clock, wall, event
        self.active, self.pending = True, None
        self.capture = None
        self.sequence, self.failures = 0, 0
        self.next_capture, self.last_capture, self.warned = 0., None, -math.inf
        self.metadata = dict(**self.identity, active=True, sequence=0, target_fps=FPS,
                             width=SIZE[0], height=SIZE[1], fps=0, warning=None)
        try:
            self.output.mkdir(parents=True, exist_ok=False)
            self._metadata()
        except Exception:
            self.active = False  # Optional producer startup never fails playback.

    def _metadata(self):
        temp = self.output / 'status.tmp'
        temp.write_text(json.dumps(self.metadata, allow_nan=False), encoding='utf-8')
        temp.replace(self.output / 'status.json')

    def _warning(self, code):
        self.failures += 1
        self.metadata.update(warning=code, skipped_frames=self.failures)
        try:
            self._metadata()
            if self.event and self.clock() - self.warned >= 5:
                self.warned = self.clock()
                self.event('LIVE_CAPTURE_WARNING', reason_code=code)
        except Exception:
            pass

    def pump(self, request_capture):
        if not self.active or self.clock() < self.next_capture:
            return
        if self.pending is not None:
            if self.clock() - self.pending[1] > 2 and not self.pending[2]:
                self.pending[2] = True
                self._warning('LIVE_CAPTURE_PENDING')
            return  # A stalled GPU callback must not queue unbounded captures.
        token = object()
        self.pending = [token, self.clock(), False]
        self.next_capture = self.clock() + 1 / FPS

        def callback(buffer, size, width, height, byte_format=None):
            if not self.active or not self.pending or self.pending[0] is not token:
                return
            try:
                from PIL import Image
                rgba = viewport_rgba(buffer, size, width, height)
                picture = Image.frombytes('RGBA', (width, height), rgba).convert('RGB')
                picture.thumbnail(SIZE)
                encoded = io.BytesIO()
                picture.save(encoded, format='JPEG', quality=QUALITY)
                data = encoded.getvalue()
                temp = self.output / 'frame.tmp'
                temp.write_bytes(data)
                temp.replace(self.output / 'latest.jpg')
                now = self.clock()
                fps = min(FPS, 1 / max(1e-6, now - self.last_capture)) if self.last_capture is not None else 0
                self.sequence += 1
                self.metadata.update(sequence=self.sequence, sha256=hashlib.sha256(data).hexdigest(),
                    captured_at=datetime.fromtimestamp(self.wall(), timezone.utc).isoformat(),
                    width=picture.width, height=picture.height, fps=round(fps, 1), warning=None)
                self._metadata()
                self.last_capture = now
            except Exception:
                self._warning('LIVE_CAPTURE_FRAME_SKIPPED')
            finally:
                self.pending = None
                self.capture = None

        try:
            self.capture = request_capture(callback)
        except Exception:
            self.pending = None
            self._warning('LIVE_CAPTURE_API_UNAVAILABLE')

    def close(self):
        self.active, self.pending = False, None
        self.capture = None
        self.metadata.update(active=False)
        try:
            self._metadata()
        except Exception:
            pass
