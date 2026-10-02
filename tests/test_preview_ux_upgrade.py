"""Renderer upgrade preserves admitted native/source/approval evidence; fake only."""
import copy
import json
from pathlib import Path
import pytest

from backend.refresh_preview_ux import refresh
from backend.services.current_preview_gate import read,sha,verify_preview
from tests.test_simulator_stp_client import fixture


def test_stp_red_connected_curve_preserves_source_nine_xyz_and_rollback_style():
    from types import SimpleNamespace
    import numpy as np
    from backend.services.preview_visual_style import define_polyline,prediction_style
    points=np.arange(27,dtype=np.float32).reshape(9,3)*.001
    before=points.copy();record={}
    class Curve:
        def __getattr__(self,name):return lambda value:record.update({name:value})
    def define(stage,path):record.update(stage=stage,path=path);return Curve()
    usd=SimpleNamespace(BasisCurves=SimpleNamespace(Define=define))
    gf=SimpleNamespace(Vec3f=lambda *p:tuple(p))
    style=prediction_style('dataset_stp')
    define_polyline('stage','/VLA_PREDICTED_9',points,style['color'],style['width_m'],usd_geom=usd,gf=gf)
    assert record['CreateTypeAttr']=='linear' and record['CreateWrapAttr']=='nonperiodic'
    assert record['CreateCurveVertexCountsAttr']==[9]
    assert np.array_equal(np.asarray(record['CreatePointsAttr']),before) and np.array_equal(points,before)
    assert record['CreateDisplayColorAttr']==[(1.,.015,.025)] and record['CreateWidthsAttr']==[.006]
    assert style['marker_radius_m']<style['width_m']/2
    assert prediction_style('dataset_v2')==prediction_style('legacy')
    assert prediction_style('legacy')['color']==(1.,.22,.04)


def old_release(client,job,monkeypatch,kind='robot'):
    claim=client.prepare(job_id=job.id,kind=kind);d=read(claim['path'])
    previous={k:v for k,v in d['owned_code'].items() if k!='backend/services/preview_visual_style.py'}
    previous['backend/current_vla_isaac_preview.py']='a'*64
    d['owned_code']=previous
    Path(claim['path']).write_text(json.dumps(d));claim['sha256']=sha(claim['path'])
    cache=client.settings.project/'.cache/simulator-stp/readiness'/d['artifact_id']/(kind+'.json')
    cache.write_text(json.dumps(claim))
    monkeypatch.setitem(__import__('backend.refresh_preview_ux',fromlist=['PRE_UX_OWNED_CODE']).PRE_UX_OWNED_CODE,'dataset_stp',copy.deepcopy(previous))
    return claim,d,cache


@pytest.mark.parametrize('kind',['path','robot'])
def test_renderer_refresh_reuses_every_native_source_file(tmp_path,monkeypatch,kind):
    client,job,attempt=fixture(tmp_path);old,d,cache=old_release(client,job,monkeypatch,kind)
    package=Path(d['package']).parent
    protected=[p for p in package.rglob('*') if p.is_file()]+[Path(old['path']),attempt/'trajectory.npz',client.storage.artifact_path('jobs',job.id,'.json'),client.storage.artifact_path('masks',job.mask.id)]
    before={p:sha(p) for p in protected}
    fresh=refresh(d['artifact_id'],project=client.settings.project,kind=kind)
    new,_,_=verify_preview(fresh,project=client.settings.project)
    assert fresh!=old and new['package_id']==d['package_id']
    assert new['source_to_scene']==d['source_to_scene'] and new['playback']==d['playback']
    assert new['orientation_source']=='simulator_stp_policy' and not new['vla_orientation']
    assert new['ux_renderer_refresh']['native_recomputed'] is False
    assert all(sha(p)==h for p,h in before.items())
    assert refresh(d['artifact_id'],project=client.settings.project,kind=kind)==fresh
    assert len(client.builder.calls)==1 and not client.runtime.calls


@pytest.mark.parametrize('change',['unknown_release','mask','source','approval'])
def test_upgrade_cannot_rebind_changed_source_or_unknown_release(tmp_path,monkeypatch,change):
    client,job,attempt=fixture(tmp_path);old,d,cache=old_release(client,job,monkeypatch)
    if change=='unknown_release':
        d['owned_code']['backend/current_vla_isaac_preview.py']='f'*64
        Path(old['path']).write_text(json.dumps(d));old['sha256']=sha(old['path']);cache.write_text(json.dumps(old))
    elif change=='mask':client.storage.artifact_path('masks',job.mask.id).write_bytes(b'changed mask')
    elif change=='source':(attempt/'trajectory.npz').write_bytes(b'changed source XYZ')
    else:job.mask.approved_at=None;client.storage.save_job(job)
    with pytest.raises((ValueError,KeyError,TypeError)):
        refresh(d['artifact_id'],project=client.settings.project)
    assert read(cache)==old and len(client.builder.calls)==1 and not client.runtime.calls
