"""Dataset-v2 identity boundary, independent of the legacy policy registry."""
from pathlib import Path
import re

from backend.services.dataset_sample import PAIRINGS


class Simulator2ContractError(ValueError):
    """Stdlib-only: usable inside the Isaac launch gate before app/import setup."""
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)

JOINTS = {'B': 'Butt', 'C': 'Corner', 'E': 'Edge', 'L': 'Lap', 'T': 'Tee'}
FAMILIES = tuple(f'{j}_{p}' for j in JOINTS for p in PAIRINGS)
NATIVE_FILES = ('run_welding_sample.py', 'welding_scene_layout.py', 'welding_contact_fixture.py',
    'welding_workpiece.py', 'welding_prediction.py', 'welding_tool_geometry.py',
    'welding_round_orientation.py', 'prepare_rb5_h5_trajectory.py',
    'rbpodo_description/robots/rb10_1300e_u.urdf', 'ATU01035_welding_tool.usd')


def identity(sample):
    match = re.fullmatch(r'([BCELT])_(PP|PR|PS|RR|RS|SS)_(\d{2}|M)_(\d{4})', sample)
    if not match or int(match[4]) == 0 or (match[3] != 'M' and int(match[3]) == 0):
        raise Simulator2ContractError('SIMULATOR2_SAMPLE_UNSUPPORTED', 'Dataset Simulator v2 does not support this sample identity.')
    joint, pairing, thickness, _ = match.groups()
    folder = 'M(Mixed)' if thickness == 'M' else f'{thickness}({int(thickness)}mm)'
    return f'{joint}_{pairing}', Path(JOINTS[joint]) / PAIRINGS[pairing] / folder / sample


def exact_assets(root, sample):
    _, relative = identity(sample)
    root = Path(root).resolve()
    other = root / '1.데이터/Other/Other'
    result = []
    for category, extension, code in (('로봇티칭데이터', '.h5', 'SIMULATOR2_H5_MISSING'),
                                      ('모델링 데이터', '.obj', 'SIMULATOR2_OBJ_MISSING')):
        path = other / category / relative / (sample + extension)
        if not path.is_file():
            raise Simulator2ContractError(code, 'The exact current sample asset is missing.')
        if path.resolve() != path.absolute() or not path.resolve().is_relative_to(root) or path.stem != sample:
            raise Simulator2ContractError(code, 'The exact current sample asset binding is invalid.')
        result.append(path)
    return tuple(result)
