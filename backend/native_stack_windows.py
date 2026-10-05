from pathlib import Path
from backend.services.environment import PROJECT, backend_env_values
DATASET = Path(backend_env_values().get('WELD_DATASET_ROOT') or PROJECT/'.cache/unconfigured-dataset').resolve()
"""Compatibility operator entry; use scripts/configure_release.py for this release."""
def prepare():
    raise ValueError('Use scripts/configure_release.py --sample-id SAMPLE_ID; root .env controls all paths')
if __name__=='__main__':
    prepare()
