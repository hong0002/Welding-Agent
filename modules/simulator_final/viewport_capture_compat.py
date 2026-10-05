"""Mandatory native viewport PNG transport; no scene/camera/motion policy.

Kit's file writer receives an ASCII temporary path. Python validates the PNG
and atomically copies it to the original Unicode destination. No capture retry.
"""
import asyncio
import binascii
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import time
import zlib


class CaptureError(RuntimeError):
    def __init__(self, code, cause=None):
        self.code = code
        super().__init__(code + (': ' + type(cause).__name__ + ': ' + str(cause) if cause else ''))


def png_dimensions(data):
    """Decode/check the native RGBA8/RGB8 PNG stream without a new dependency."""
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('PNG signature missing')
    offset, compressed, dimensions, ended = 8, bytearray(), None, False
    while offset + 12 <= len(data):
        size = struct.unpack_from('>I', data, offset)[0]
        kind = data[offset+4:offset+8]; end = offset+8+size
        if end+4 > len(data) or binascii.crc32(data[offset+4:end]) & 0xffffffff != struct.unpack_from('>I',data,end)[0]:
            raise ValueError('Incomplete PNG or CRC mismatch')
        payload = data[offset+8:end]
        if kind == b'IHDR':
            width,height,bits,color,compression,filtering,interlace = struct.unpack('>IIBBBBB',payload)
            if not (0 < width <= 4096 and 0 < height <= 4096 and bits == 8 and color in (2,6)
                    and compression == filtering == interlace == 0):
                raise ValueError('Unsupported native capture PNG')
            dimensions = width,height,3 if color == 2 else 4
        elif kind == b'IDAT':
            compressed.extend(payload)
        elif kind == b'IEND':
            ended = True; break
        offset = end+4
    if not dimensions or not ended:
        raise ValueError('PNG chunks missing')
    width,height,channels = dimensions
    decoder = zlib.decompressobj()
    stride = 1 + width*channels
    raw = decoder.decompress(compressed, height*stride+1)
    if not decoder.eof or len(raw) != height*stride or any(raw[i] > 4 for i in range(0,len(raw),stride)):
        raise ValueError('PNG pixel stream incomplete')
    return width,height


def capture_png(destination, *, viewport, request_capture, update, clock=time.monotonic,
                timeout=20., staging_factory=None, task_factory=None, event=None):
    """Dependency-injected transport, usable with fake tasks in offline tests."""
    destination = Path(destination)
    task = None
    phase = 'VIEWPORT_NOT_FOUND'
    def emit(**value):
        if event: event(**value)
    try:
        if viewport is None:
            raise CaptureError('VIEWPORT_NOT_FOUND')
        phase = 'CAPTURE_COPY_FAILED'
        destination.parent.mkdir(parents=True,exist_ok=True)
        phase = 'CAPTURE_ASCII_PATH_UNAVAILABLE'
        if not str(Path(tempfile.gettempdir()).resolve()).isascii():
            raise CaptureError(phase)
        staging = Path(staging_factory() if staging_factory else tempfile.mkdtemp(prefix='weld_capture_')).resolve()
        if not str(staging).isascii():
            raise CaptureError(phase)
        try:
            temporary = staging/'frame.png'
            viewport.set_texture_resolution((1280,960))
            for _ in range(40): update()  # Existing native warm-up, unchanged.
            phase = 'CAPTURE_TASK_EXCEPTION'
            capture = request_capture(viewport,str(temporary))
            task = (task_factory or asyncio.ensure_future)(capture.wait_for_result(completion_frames=0))
            emit(stage='capture_started',ascii_path=True,destination_ascii=str(destination).isascii())
            deadline = clock()+timeout
            while clock() < deadline:
                update()
                if task.done():
                    error = task.exception()
                    if error: raise CaptureError('CAPTURE_TASK_EXCEPTION',error)
                if task.done() and temporary.is_file():
                    phase = 'CAPTURE_DECODE_ERROR'
                    try: width,height = png_dimensions(temporary.read_bytes())
                    except (OSError,ValueError,struct.error,zlib.error):
                        # File writing is asynchronous even after the SDK task is
                        # done. Do not decode a partially written file as success.
                        time.sleep(.01); continue
                    phase = 'CAPTURE_COPY_FAILED'
                    pending = destination.with_suffix('.capture.tmp')
                    try:
                        shutil.copyfile(temporary,pending)
                        os.replace(pending,destination)
                    finally:
                        pending.unlink(missing_ok=True)
                    emit(stage='capture_complete',ascii_path=True,width=width,height=height,
                         bytes=destination.stat().st_size)
                    return dict(width=width,height=height,ascii_path=True)
                time.sleep(.01)
            if temporary.is_file(): raise CaptureError('CAPTURE_DECODE_ERROR')
            raise CaptureError('CAPTURE_FILE_NOT_WRITTEN' if task.done() else 'CAPTURE_TIMEOUT')
        finally:
            if task is not None and not task.done(): task.cancel()
            # Only delete this helper's own verified temporary directory.
            temp_root = Path(tempfile.gettempdir()).resolve()
            if (staging_factory is None and staging.is_relative_to(temp_root)
                    and staging != temp_root and staging.name.startswith('weld_capture_')):
                shutil.rmtree(staging,ignore_errors=True)
    except CaptureError as exc:
        emit(stage='capture_failed',reason_code=exc.code,exception_class=type(exc).__name__,message=str(exc))
        raise
    except Exception as exc:
        emit(stage='capture_failed',reason_code=phase,exception_class=type(exc).__name__,message=str(exc))
        raise CaptureError(phase,exc) from exc


def capture_native_frame(app,destination):
    from omni.kit.viewport.utility import get_active_viewport,capture_viewport_to_file
    destination = Path(destination)
    def event(**value):
        # JSON's ASCII escapes preserve exception text even across a mixed-codepage
        # native stdout pipeline. No model payloads or environment values here.
        value['label'] = destination.stem
        print('[CAPTURE_DIAGNOSTIC] '+json.dumps(value,ensure_ascii=True),flush=True)
        try:
            destination.parent.mkdir(parents=True,exist_ok=True)
            with (destination.parent/'capture.diagnostics.jsonl').open('a',encoding='utf-8') as stream:
                stream.write(json.dumps(value,ensure_ascii=True)+'\n')
        except OSError as exc:
            # Preserve the primary capture reason if its output directory itself
            # cannot be written; stdout still retains the original diagnostic.
            print('[CAPTURE_DIAGNOSTIC] '+json.dumps(dict(stage='diagnostic_write_failed',
                  exception_class=type(exc).__name__),ensure_ascii=True),flush=True)
    return capture_png(destination,viewport=get_active_viewport(),
                       request_capture=capture_viewport_to_file,update=app.update,event=event)
