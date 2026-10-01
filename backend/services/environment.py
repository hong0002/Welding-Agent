"""Backend-owned dotenv source. Never mutates/export secrets into os.environ."""
from pathlib import Path
from dotenv import dotenv_values

PROJECT = Path(__file__).resolve().parents[2]


def backend_env_values(path=None):
    path = Path(path) if path is not None else PROJECT / '.env'
    return dotenv_values(path, encoding='utf-8-sig', interpolate=False) if path.is_file() else {}
