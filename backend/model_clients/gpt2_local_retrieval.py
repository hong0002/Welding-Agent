"""Direct native final-reference retrieval; CPU compatibility at GPU transfer only."""
from functools import lru_cache
import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys
import time


def gpu_available(faiss):
    return hasattr(faiss, 'StandardGpuResources') and hasattr(faiss, 'index_cpu_to_gpu')


def configure_faiss(runtime, faiss):
    """Leave the GPU branch unchanged. CPU branch loads the identical index bytes."""
    if gpu_available(faiss):
        return 'GPU'

    @lru_cache(maxsize=1)
    def resources():
        return None

    @lru_cache(maxsize=32)
    def cpu_index(path, device_id=0):
        try:
            return faiss.read_index(str(path))
        except RuntimeError:
            # Windows FAISS fopen cannot open Korean paths; no alias/copy/index edit.
            import numpy as np
            return faiss.deserialize_index(np.fromfile(path, dtype='uint8'))

    runtime.resources = resources
    runtime.gpu_index = cpu_index
    return 'CPU_FALLBACK'


def load_runtime(root):
    """Original .py source only. Resident modules, sockets and locks are never loaded."""
    root = Path(root).resolve()
    import faiss
    cpu = not gpu_available(faiss)

    class SourceOnly(importlib.machinery.SourceFileLoader):
        def get_code(self, fullname):
            source = self.get_data(self.path).decode('utf-8')
            if fullname == 'service.action_runtime' and cpu:
                # Lift only the native GPU-only admission guard in owned memory.
                # Search/embedding/filter/rank/reference bodies remain native.
                before = "if not hasattr(faiss, 'StandardGpuResources'):"
                if source.count(before) != 1:
                    raise RuntimeError('LOCAL_FAISS_BOUNDARY_CHANGED')
                source = source.replace(before, before[:-1] + ' and not _WELD_FAISS_CPU_COMPAT:')
                # A future import must stay first; supply the flag via module globals.
            return compile(source, self.path, 'exec', dont_inherit=True)

        def exec_module(self, module):
            module._WELD_FAISS_CPU_COMPAT = cpu
            super().exec_module(module)

    class Finder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname != 'service' and not fullname.startswith('service.'):
                return None
            if fullname not in ('service', 'service.retrieve', 'service.action_runtime'):
                raise ImportError('LOCAL_RESIDENT_MODULE_FORBIDDEN')
            file = root.joinpath(*fullname.split('.'))
            package = file.is_dir()
            file = file/'__init__.py' if package else file.with_suffix('.py')
            if not file.is_file():
                raise FileNotFoundError(file)
            return importlib.util.spec_from_file_location(fullname, file,
                loader=SourceOnly(fullname, str(file)),
                submodule_search_locations=[str(file.parent)] if package else None)

    # Dedicated native child: never mix an unrelated already imported service.
    for name in ('service', 'service.retrieve', 'service.action_runtime'):
        existing = sys.modules.get(name)
        if existing and not Path(existing.__file__).resolve().is_relative_to(root):
            raise RuntimeError('LOCAL_SERVICE_SOURCE_MISMATCH')
    finder = Finder();sys.meta_path.insert(0, finder)
    try:
        runtime = importlib.import_module('service.action_runtime')
        retrieve = importlib.import_module('service.retrieve')
    finally:
        sys.meta_path.remove(finder)
    runtime.ROOT = retrieve.ROOT = root
    runtime.IMAGE_DB = retrieve.DEFAULT_DB = root/'incoming/database_source/welding_train_v1'
    runtime.IMAGE_INDEX = retrieve.DEFAULT_INDEX = root/'index/welding_train_v1/dinov2_base_v1'
    runtime.ACTION_SOURCE = root/'incoming/action_source/welding_actions_v1/actions.jsonl'
    runtime.ACTION_INDEX = root/'index/welding_actions_v1/multilingual_e5_base_v1'
    mode = configure_faiss(runtime, faiss)
    return runtime, mode


class LocalFinalRetrieval:
    def __init__(self, root, *, evidence, shared_root=None):
        self.root = Path(root).resolve()
        self.shared_root = Path(shared_root).resolve() if shared_root else self.root.parent
        self.evidence = Path(evidence)
        self.evidence.mkdir(parents=True, exist_ok=True)
        self.runtime, self.mode = load_runtime(root)
        self.calls = 0

    def retrieve_actions(self, config, payload):
        """The original core returns original IDs/scores/actions in original order."""
        self.calls += 1
        start = time.monotonic()
        result = self.runtime.search(payload)
        if result['index_split'].lower() not in ('train', 'training') or any(
                item['sample_id'] == payload['sample_id'] for item in result['results']):
            raise ValueError('LOCAL_TRAIN_SELF_EXCLUSION_INVALID')
        (self.evidence/'local_retrieval_provenance.json').write_text(json.dumps(dict(
            backend='vlm_embedding_server',reference_stage='vlm_project4',mode='LOCAL',
            faiss_mode=self.mode,source_changed=False,index_rebuilt=False,ranking_changed=False,
            calls=self.calls,seconds=round(time.monotonic()-start,3),
            top_k=[{'sample_id':v['sample_id'],'fused_score':v['fused_score'],'ranks':v['ranks']} for v in result['results']],
            ssh_calls=0,resident_calls=0),ensure_ascii=False,indent=2),encoding='utf-8')
        return result

    def reference_helper(self, cache=None):
        # vlm_project4's actual original helper is shared. Replace its transport only.
        shared = getattr(self, 'shared_root', self.root.parent)/'vlm_project2/fewshot_examples.py'
        module_name = 'vlm_project2.fewshot_examples'
        module = importlib.util.module_from_spec(importlib.util.spec_from_file_location(module_name,shared))
        sys.modules[module_name] = module
        exec(compile(shared.read_bytes(),str(shared),'exec'),module.__dict__)
        module.retrieve_actions = self.retrieve_actions
        original = module.prepare_examples
        if cache is None:
            return original
        cache = Path(cache)

        def prepare(config,data_root,sample_id,instruction,polylines,sizes,directory,frozen_cache=None):
            # Reuse a genuine smoke artifact only through the original native cache path.
            # Compare the complete native query/config fingerprint before any GPT call.
            import hashlib
            settings = config['retrieval']
            payload = dict(sample_id=sample_id,refined_search_text_ko=instruction,
                top_k=settings['top_k'],candidate_pool=settings['candidate_pool'],
                weights=settings['weights'],rrf_constant=settings.get('rrf_constant',60),
                mask_available=any(polylines.values()),mask_descriptor=module.mask_descriptor(polylines,sizes),
                accepted_masks=polylines)
            identity = {k:config['server'][k] for k in ('ssh_alias','remote_root','remote_python')}
            expected = hashlib.sha256(json.dumps([identity,payload],sort_keys=True).encode()).hexdigest()
            fixed = json.loads(cache.read_text(encoding='utf-8'))
            if fixed.get('request_fingerprint') != expected or fixed.get('request') != payload:
                raise ValueError('LOCAL_RETRIEVAL_CACHE_MISMATCH')
            if fixed['response'].get('index_split') != 'train' or any(
                    v['sample_id']==sample_id for v in fixed['response']['results']):
                raise ValueError('LOCAL_RETRIEVAL_CACHE_INVALID')
            return original(config,data_root,sample_id,instruction,polylines,sizes,directory,frozen_cache=cache)
        return prepare
