"""Backend-owned native versions; no automatic fallback or browser-selected paths."""
from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class NativeProfile:
    name: str
    repository: str
    microseconds: bool = False
    query_image: str = 'query_masks.jpg'

    def sessions(self, root, sample_id):
        stamp = r'\d{8}_\d{6}' + (r'_\d{6}' if self.microseconds else '')
        pattern = stamp + '_' + re.escape(sample_id)
        return {p.resolve() for p in Path(root).glob('*_'+sample_id)
                if p.is_dir() and re.fullmatch(pattern, p.name)}


def native_profile(stage, backend):
    if stage == 'segment' and backend == 'native_v2':
        return NativeProfile('native_v2', 'vlm_segment2', True)
    if stage == 'rough3d' and backend == 'native_3d_v3':
        return NativeProfile('native_3d_v3', 'vlm_trajectory3', True, 'query_views.jpg')
    permitted = {'segment': {'native', 'real', 'native_v1'},
                 'rough': {'native', 'real'}, 'rough3d': {'native', 'real', 'native_3d_v2'}}
    if backend not in permitted.get(stage, set()):
        raise ValueError('Unsupported native version')
    return NativeProfile({'segment':'native_v1','rough':'baseline_2d','rough3d':'native_3d_v2'}[stage],
                         {'segment':'vlm_segment','rough':'vlm_trajectory','rough3d':'vlm_trajectory2'}[stage])
