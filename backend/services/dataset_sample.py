"""Exact Other/Other dataset naming contract; no directory search or aliases."""
from dataclasses import dataclass
from pathlib import Path
import re

JOINTS = {'B': 'Butt', 'L': 'Lap', 'T': 'Tee'}
PAIRINGS = {'PP': 'PP(Plate-Plate)', 'PR': 'PR(Plate-Round)',
            'PS': 'PS(Plate-Structural)', 'RR': 'RR(Round-Round)',
            'RS': 'RS(Round-Structural)', 'SS': 'SS(Structural-Structural)'}


@dataclass(frozen=True)
class SampleIdentity:
    sample_id: str
    joint_type: str
    geometry: str
    thickness: str
    index: str

    @property
    def family(self):
        return f'{self.joint_type}_{self.geometry}'

    @property
    def relative(self):
        return (Path(JOINTS[self.joint_type]) / PAIRINGS[self.geometry] /
                f'{self.thickness}({int(self.thickness)}mm)' / self.sample_id)


def resolve_sample(sample_id):
    match = re.fullmatch(r'([BLT])_(PP|PR|PS|RR|RS|SS)_(\d{2})_(\d{4})', sample_id)
    if not match or int(match[3]) == 0 or int(match[4]) == 0:
        raise ValueError('Unsupported dataset sample identity')
    return SampleIdentity(sample_id, *match.groups())


def exact_assets(dataset_root, sample_id):
    identity = resolve_sample(sample_id)
    other = Path(dataset_root).resolve() / '1.데이터/Other/Other'
    return (other / '로봇티칭데이터' / identity.relative / f'{sample_id}.h5',
            other / '모델링 데이터' / identity.relative / f'{sample_id}.obj')
