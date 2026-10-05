from types import SimpleNamespace
import hashlib
import json
import sys
import pytest
from backend.model_clients.gpt2_local_retrieval import configure_faiss, gpu_available


def test_gpu_branch_preserves_original_boundaries():
    resources = lambda: 'original-gpu-resource'
    index = lambda *args: 'original-gpu-index'
    runtime = SimpleNamespace(resources=resources,gpu_index=index)
    faiss = SimpleNamespace(StandardGpuResources=object,index_cpu_to_gpu=lambda *args:None)
    assert gpu_available(faiss)
    assert configure_faiss(runtime,faiss)=='GPU'
    assert runtime.resources is resources and runtime.gpu_index is index


def test_cpu_branch_retains_native_index_search_and_cache():
    calls=[]
    class Index:
        def search(self,query,count):return query,count
    index=Index()
    faiss=SimpleNamespace(read_index=lambda path:(calls.append(path) or index))
    runtime=SimpleNamespace()
    assert not gpu_available(faiss)
    assert configure_faiss(runtime,faiss)=='CPU_FALLBACK'
    assert runtime.resources() is None
    assert runtime.gpu_index('existing.faiss') is index
    assert runtime.gpu_index('existing.faiss') is index
    assert calls==['existing.faiss']
    assert runtime.gpu_index('existing.faiss').search('unchanged-query',1199)==('unchanged-query',1199)


@pytest.fixture
def frozen_helper(tmp_path, monkeypatch):
    from backend.model_clients.gpt2_local_retrieval import LocalFinalRetrieval
    shared=tmp_path/'vlm_project2';shared.mkdir()
    (shared/'fewshot_examples.py').write_text(
        'def mask_descriptor(polylines,sizes): return [1,2]\n'
        'def prepare_examples(*args,frozen_cache=None): return frozen_cache\n',encoding='utf-8')
    # Preserve any surrounding native module; this fixture never loads encoders.
    monkeypatch.setitem(sys.modules,'vlm_project2.fewshot_examples',None)
    local=object.__new__(LocalFinalRetrieval)
    local.root=tmp_path/'vlm_embedding_server'
    local.calls=0
    config={'server':dict(ssh_alias='LOCAL_SOURCE_DIRECT',remote_root='local',remote_python='fixed'),
            'retrieval':dict(top_k=3,candidate_pool=20,weights={'mask':1})}
    payload=dict(sample_id='query',refined_search_text_ko='instruction',top_k=3,candidate_pool=20,
                 weights={'mask':1},rrf_constant=60,mask_available=True,mask_descriptor=[1,2],
                 accepted_masks={'F':[[[1,2],[3,4]]]})
    fingerprint=hashlib.sha256(json.dumps([config['server'],payload],sort_keys=True).encode()).hexdigest()
    data=dict(request_fingerprint=fingerprint,request=payload,
              response=dict(index_split='train',results=[dict(sample_id='reference')]))
    cache=tmp_path/'retrieval.json'
    cache.write_text(json.dumps(data),encoding='utf-8')
    return local,config,payload,cache,data


def test_genuine_smoke_cache_uses_original_frozen_cache_without_second_search(frozen_helper):
    local,config,payload,cache,_=frozen_helper
    helper=local.reference_helper(cache)
    assert helper(config,'data','query','instruction',payload['accepted_masks'],{},'output')==cache
    assert local.calls==0


def test_changed_instruction_cannot_reuse_smoke_cache(frozen_helper):
    local,config,payload,cache,_=frozen_helper
    with pytest.raises(ValueError,match='LOCAL_RETRIEVAL_CACHE_MISMATCH'):
        local.reference_helper(cache)(config,'data','query','changed',payload['accepted_masks'],{},'output')
    assert local.calls==0
