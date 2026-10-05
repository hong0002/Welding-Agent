"""Nonblocking viewport observer for original native playback. No scene/motion edits."""
from backend.services.preview_live_producer import LiveFrameProducer


def request_viewport_frame(callback):
    import omni.ui as ui
    from omni.kit.viewport.utility import get_active_viewport, capture_viewport_to_buffer
    viewport = get_active_viewport()
    if viewport is None: raise RuntimeError('Viewport unavailable')
    def rgba(buffer, size, width, height, byte_format):
        if byte_format != ui.TextureFormat.RGBA8_UNORM:
            callback(b'',0,0,0)
        else: callback(buffer,size,width,height,byte_format)
    # Capture the original native viewport; do not change camera or resolution.
    return capture_viewport_to_buffer(viewport,rgba)


class NativeLiveCapture:
    def __init__(self, output, identity, stop_file, *, request_capture=request_viewport_frame):
        self.output, self.identity, self.stop_file = output, identity, stop_file
        self.request_capture = request_capture
        self.producer = self.app = self.original_update = None

    def start(self, app):
        if self.producer: return
        self.producer = LiveFrameProducer(self.output,self.identity,fps=4)
        self.app, self.original_update = app, app.update
        def update(*args, **kwargs):
            result = self.original_update(*args,**kwargs)  # Native failure policy unchanged.
            if self.stop_file.exists(): self.producer.close()
            else: self.producer.pump(self.request_capture)
            return result
        try: app.update = update
        except Exception:
            self.producer.close()
            print('[CURRENT_PREVIEW] LIVE_CAPTURE_API_UNAVAILABLE',flush=True)

    def close(self):
        if self.producer: self.producer.close()
        if self.app and self.original_update: self.app.update = self.original_update
