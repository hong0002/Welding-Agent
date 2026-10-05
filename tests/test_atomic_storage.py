"""Windows write contention must not expose partial or overwritten snapshots."""
import pytest
from backend.services import storage


def denied(winerror=None):
    error=PermissionError('replacement denied')
    if winerror is not None:error.winerror=winerror
    return error


def test_brief_windows_denial_keeps_atomic_old_then_new_snapshot(tmp_path,monkeypatch):
    path=tmp_path/'job.json';path.write_text('{"revision":1}',encoding='utf-8')
    replace=storage.os.replace;calls=[]
    def busy_then_replace(source,destination):
        assert path.read_text(encoding='utf-8')=='{"revision":1}'
        assert source.read_text(encoding='utf-8')=='{"revision":2}'
        calls.append((source,destination))
        if len(calls)<3:raise denied(5)
        replace(source,destination)
    monkeypatch.setattr(storage.os,'replace',busy_then_replace)
    monkeypatch.setattr(storage.time,'sleep',lambda _:None)
    storage.LocalStorage._write_json(path,'{"revision":2}')
    assert path.read_text(encoding='utf-8')=='{"revision":2}'
    assert len({source for source,_ in calls})==1
    assert not list(tmp_path.glob('*.tmp'))


@pytest.mark.parametrize('winerror',[None,5,32,33])
def test_persistent_denial_never_rewrites_or_deletes_original(tmp_path,monkeypatch,winerror):
    path=tmp_path/'job.json';path.write_text('original',encoding='utf-8');calls=[]
    def fail(*args):calls.append(args);raise denied(winerror)
    monkeypatch.setattr(storage.os,'replace',fail)
    monkeypatch.setattr(storage.time,'sleep',lambda _:None)
    with pytest.raises(PermissionError):storage.LocalStorage._write_json(path,'new')
    assert path.read_text(encoding='utf-8')=='original'
    assert len(calls)==(1 if winerror is None else 5)
    assert not list(tmp_path.glob('*.tmp'))
