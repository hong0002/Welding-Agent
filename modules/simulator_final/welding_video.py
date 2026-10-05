"""Capture the active viewport's rendered color buffer, without desktop UI."""
import ctypes
import json
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
import numpy as np


def recording_label(solution_path, layout='legacy'):
    report_path = Path(solution_path).parent / 'report.json'
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
    sample = report.get('sample_id', Path(solution_path).stem)
    prediction = report.get('prediction') or {}
    if prediction.get('source_directory'):
        export = Path(prediction['source_directory']).parent
        method = f'{export.parent.name}_{export.name}'
    else:
        method = 'GT' if report else 'unknown'
    return re.sub(r'[^\w.\-]+', '_', f'{sample}_{method}_{layout}')[:190]


def copy_video(path, directory, label):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    target = directory / f'{label}_{stamp}.mp4'
    # Exclusive creation prevents overwriting another recording.
    with target.open('xb') as destination, Path(path).open('rb') as source:
        shutil.copyfileobj(source, destination)
    print(f'[VIDEO COPY] {target}', flush=True)
    return target


class ViewportVideo:
    def __init__(self, app, path, fps=30, archive_dir=None, archive_label=None):
        import cv2
        from omni.kit.viewport.utility import get_active_viewport, capture_viewport_to_buffer
        self.cv2 = cv2
        self.app = app
        self.viewport = get_active_viewport()
        if self.viewport is None:
            raise RuntimeError('Video recording requires an active rendered viewport')
        self.capture = capture_viewport_to_buffer
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.partial = self.path.with_name(self.path.stem + '.partial.mp4')
        self.fps = fps
        self.archive_dir = archive_dir
        self.archive_label = archive_label or self.path.stem
        self.frames = 0
        self.writer = None
        self.size = None
        self.camera = str(self.viewport.camera_path)

    def add_frame(self):
        result = {}
        def receive(buffer, buffer_size, width, height, byte_format):
            try:
                width, height = int(width), int(height)
                if int(buffer_size) != width * height * 4:
                    raise RuntimeError(f'Expected RGBA8 viewport buffer, got {byte_format}, {buffer_size} bytes')
                if type(buffer).__name__ == 'PyCapsule':
                    get_name = ctypes.pythonapi.PyCapsule_GetName
                    get_name.restype = ctypes.c_char_p
                    get_name.argtypes = [ctypes.py_object]
                    get_pointer = ctypes.pythonapi.PyCapsule_GetPointer
                    get_pointer.restype = ctypes.c_void_p
                    get_pointer.argtypes = [ctypes.py_object, ctypes.c_char_p]
                    pointer = get_pointer(buffer, get_name(buffer))
                    if not pointer: raise RuntimeError('Empty viewport capture buffer')
                    rgba = np.ctypeslib.as_array((ctypes.c_uint8 * int(buffer_size)).from_address(pointer))
                else:
                    rgba = np.frombuffer(buffer, dtype=np.uint8)
                result['rgba'] = rgba.reshape(height, width, 4).copy()
            except Exception as exc:
                result['error'] = exc
        # Hold this capture object until its callback delivers the copied buffer.
        capture = self.capture(self.viewport, receive, is_hdr=False)
        deadline = time.monotonic() + 30
        while not result:
            if not self.app.is_running(): raise RuntimeError('Simulator closed during video capture')
            if time.monotonic() > deadline: raise RuntimeError('Viewport video capture timed out')
            self.app.update()
        if 'error' in result: raise result['error']
        rgba = result['rgba']
        if self.writer is None:
            h, w = rgba.shape[:2]
            self.size = (w // 2 * 2, h // 2 * 2)
            if min(self.size) < 2: raise RuntimeError('Viewport is too small to record')
            self.writer = self.cv2.VideoWriter(str(self.partial), self.cv2.VideoWriter_fourcc(*'mp4v'),
                                              self.fps, self.size)
            if not self.writer.isOpened(): raise RuntimeError('OpenCV could not open the MP4 encoder (mp4v)')
            print(f'[VIDEO] recording {self.path} ({self.size[0]}x{self.size[1]}, {self.fps} FPS)', flush=True)
        frame = self.cv2.cvtColor(rgba, self.cv2.COLOR_RGBA2BGR)
        if (frame.shape[1], frame.shape[0]) != self.size:
            frame = self.cv2.resize(frame, self.size)
        self.writer.write(frame)
        self.frames += 1

    def close(self, complete):
        if self.writer is not None:
            self.writer.release()
            self.writer = None
        if not self.frames: return
        if complete:
            self.partial.replace(self.path)
        saved = self.path if complete else self.partial
        saved.with_suffix('.json').write_text(json.dumps(dict(
            status='complete' if complete else 'interrupted', video=str(saved),
            fps=self.fps, frame_count=self.frames, duration_sec=self.frames/self.fps,
            resolution=self.size, camera_path_at_start=self.camera,
            capture='active viewport LdrColor; no desktop UI', timing='fixed frame trajectory progress'
        ), indent=2), encoding='utf-8')
        print(f'[VIDEO {"SAVED" if complete else "PARTIAL"}] {saved}', flush=True)
        if complete and self.archive_dir is not None:
            copy_video(saved, self.archive_dir, self.archive_label)
