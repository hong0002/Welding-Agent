"""Fake capture only: no Kit, SimulationApp, model requests or scene changes."""
import binascii
from pathlib import Path
import struct
import sys
from types import ModuleType,SimpleNamespace
import zlib

import pytest

from backend.viewport_capture_compat import capture_png,CaptureError,png_dimensions


def png():
    def chunk(kind,payload):
        return struct.pack('>I',len(payload))+kind+payload+struct.pack('>I',binascii.crc32(kind+payload)&0xffffffff)
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',4,3,8,6,0,0,0))
            +chunk(b'IDAT',zlib.compress((b'\0'+b'\xff\0\0\xff'*4)*3))+chunk(b'IEND',b''))


class Viewport:
    def set_texture_resolution(self,size): self.size=size


class Task:
    def __init__(self,done=True,error=None): self.complete,self.error,self.cancelled=done,error,False
    def done(self): return self.complete
    def exception(self): return self.error
    def cancel(self): self.cancelled=True


class Capture:
    def wait_for_result(self,completion_frames): assert completion_frames==0; return None


def fixture(tmp_path):
    stage=tmp_path/'ascii';stage.mkdir()
    clock=[0.];events=[];viewport=Viewport()
    def update():clock[0]+=.02
    return tmp_path/'한글 destination/start.png',stage,clock,events,viewport,update


def run(tmp_path,request,task=None,viewport=None):
    destination,stage,clock,events,v,update=fixture(tmp_path)
    return destination,events,lambda:capture_png(destination,viewport=v if viewport is None else viewport,
        request_capture=request,update=update,clock=lambda:clock[0],timeout=.05,
        staging_factory=lambda:stage,task_factory=lambda _:task or Task(),event=lambda **x:events.append(x))


def test_ascii_transport_to_unicode_destination(tmp_path):
    paths=[]
    def request(v,p):
        assert v.size==(1280,960); assert p.isascii()
        paths.append(p);Path(p).write_bytes(png());return Capture()
    destination,events,call=run(tmp_path,request)
    assert call()==dict(width=4,height=3,ascii_path=True)
    assert destination.read_bytes()==png()
    assert events[-1]['stage']=='capture_complete'
    assert len(paths)==1


def test_missing_viewport_no_capture(tmp_path):
    with pytest.raises(CaptureError,match='VIEWPORT_NOT_FOUND'):
        capture_png(tmp_path/'start.png',viewport=None,request_capture=lambda *a:pytest.fail('called'),update=lambda:None)


@pytest.mark.parametrize('done,code',[(True,'CAPTURE_FILE_NOT_WRITTEN'),(False,'CAPTURE_TIMEOUT')])
def test_task_completion_is_not_file_success(tmp_path,done,code):
    task=Task(done=done)
    _,events,call=run(tmp_path,lambda *a:Capture(),task=task)
    with pytest.raises(CaptureError,match=code):call()
    assert events[-1]['reason_code']==code
    assert task.cancelled is (not done)


def test_task_exception_preserved(tmp_path):
    _,events,call=run(tmp_path,lambda *a:Capture(),task=Task(error=ValueError('capture 오류')))
    with pytest.raises(CaptureError,match='CAPTURE_TASK_EXCEPTION'):call()
    assert 'capture 오류' in events[-1]['message']


def test_request_exception_preserved_no_retry(tmp_path):
    calls=[]
    def request(*a):calls.append(a);raise RuntimeError('capture API failure')
    _,events,call=run(tmp_path,request)
    with pytest.raises(CaptureError,match='CAPTURE_TASK_EXCEPTION'):call()
    assert len(calls)==1 and events[-1]['exception_class']=='RuntimeError'


@pytest.mark.parametrize('data',[b'',b'not png',png()[:-7]])
def test_incomplete_or_malformed_png(tmp_path,data):
    def request(v,p):Path(p).write_bytes(data);return Capture()
    destination,_,call=run(tmp_path,request)
    with pytest.raises(CaptureError,match='CAPTURE_DECODE_ERROR'):call()
    assert not destination.exists()


def test_copy_failure_distinct(tmp_path,monkeypatch):
    def request(v,p):Path(p).write_bytes(png());return Capture()
    destination,_,call=run(tmp_path,request)
    def fail(*args):raise PermissionError('destination access denied')
    monkeypatch.setattr('backend.viewport_capture_compat.shutil.copyfile',fail)
    with pytest.raises(CaptureError,match='CAPTURE_COPY_FAILED'):call()
    assert not destination.exists()


def test_png_validation():
    assert png_dimensions(png())==(4,3)
    damaged=bytearray(png());damaged[45]^=1
    with pytest.raises(ValueError):png_dimensions(damaged)


def test_native_missing_viewport_retains_reason_before_directory_exists(tmp_path,monkeypatch):
    from backend.viewport_capture_compat import capture_native_frame
    utility=ModuleType('omni.kit.viewport.utility')
    utility.get_active_viewport=lambda:None
    utility.capture_viewport_to_file=lambda *a:pytest.fail('capture should not be requested')
    monkeypatch.setitem(sys.modules,'omni.kit.viewport.utility',utility)
    with pytest.raises(CaptureError,match='VIEWPORT_NOT_FOUND'):
        capture_native_frame(SimpleNamespace(update=lambda:pytest.fail('no viewport')),tmp_path/'new/captures/start.png')
    assert 'VIEWPORT_NOT_FOUND' in (tmp_path/'new/captures/capture.diagnostics.jsonl').read_text()
