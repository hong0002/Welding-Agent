"""Offline import/immutable descriptor regressions; no model or Isaac launch."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from backend.refresh_preview_ux import FINAL_COMPANION_CODE, PRE_FINAL_COMPANION_SHA, refresh
from backend.services.current_preview_gate import read, sha, verify_preview
from tests.test_simulator_final_client import fixture


def test_companion_cold_import_does_not_require_backend_settings_or_dotenv():
    code = '''
import importlib.abc,sys
class BlockBackendSettings(importlib.abc.MetaPathFinder):
    def find_spec(self,name,path=None,target=None):
        if name in ('dotenv','backend.services.environment','backend.services.simulator_prediction_package'):
            raise ModuleNotFoundError(name,name=name)
sys.meta_path.insert(0,BlockBackendSettings())
from backend.services.gpt2_simulator_companion import verify_companion,write_companion
assert 'backend.services.environment' not in sys.modules
'''
    result=subprocess.run([sys.executable,'-B','-X','utf8','-c',code],
                          cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def stale_companion(client,job):
    claim=client.prepare(job_id=job.id)
    descriptor=read(claim['path'])
    descriptor['owned_code'][FINAL_COMPANION_CODE]=PRE_FINAL_COMPANION_SHA
    Path(claim['path']).write_text(json.dumps(descriptor),encoding='utf-8')
    claim['sha256']=sha(claim['path'])
    cache=client.settings.project/'.cache/simulator-final/readiness'/descriptor['artifact_id']/'robot.json'
    cache.write_text(json.dumps(claim),encoding='utf-8')
    return claim,descriptor,cache


def test_final_import_fix_reissues_descriptor_preserving_package_source_and_approval(tmp_path):
    client,job,attempt=fixture(tmp_path)
    old,descriptor,cache=stale_companion(client,job)
    protected=[p for p in attempt.rglob('*') if p.is_file()]
    protected += [p for p in Path(descriptor['package']).parent.rglob('*') if p.is_file()]
    protected += [Path(old['path']),client.storage.artifact_path('jobs',job.id,'.json'),
                  client.storage.artifact_path('masks',job.mask.id)]
    hashes={p:sha(p) for p in protected}
    with pytest.raises(ValueError):verify_preview(old,project=client.settings.project)
    new=refresh(job.vla_prediction.artifact_id,backend='dataset_final',project=client.settings.project,job_id=job.id)
    updated,_,_=verify_preview(new,project=client.settings.project)
    assert new!=old and read(cache)==new
    assert updated['package_id']==descriptor['package_id'] and updated['artifact_id']==descriptor['artifact_id']
    assert updated['ux_renderer_refresh']['reason']=='GPT2_COMPANION_BACKEND_IMPORT_REMOVED'
    assert all(sha(p)==digest for p,digest in hashes.items())
    assert len(client.builder.calls)==1 and not client.runtime.calls
    assert refresh(job.vla_prediction.artifact_id,backend='dataset_final',project=client.settings.project,job_id=job.id)==new


@pytest.mark.parametrize('mutation',['unknown_code','approval','source_npz'])
def test_import_fix_never_heals_invalid_source_or_approval(tmp_path,mutation):
    client,job,attempt=fixture(tmp_path)
    old,descriptor,cache=stale_companion(client,job)
    if mutation=='unknown_code':
        descriptor['owned_code']['backend/services/simulator2_gate.py']='0'*64
        Path(old['path']).write_text(json.dumps(descriptor),encoding='utf-8')
        old['sha256']=sha(old['path']);cache.write_text(json.dumps(old),encoding='utf-8')
    elif mutation=='approval':
        job.mask.approved_at=job.mask.approved_at.replace(year=2025);client.storage.save_job(job)
    else:(attempt/'trajectory.npz').write_bytes(b'changed native prediction')
    before=cache.read_bytes()
    with pytest.raises((ValueError,OSError)):
        refresh(job.vla_prediction.artifact_id,backend='dataset_final',project=client.settings.project,job_id=job.id)
    assert cache.read_bytes()==before and not client.runtime.calls
