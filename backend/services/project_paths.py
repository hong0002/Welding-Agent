"""Backend-owned source roots for a packaged release or original sibling layout."""
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]

def native_parent(project=PROJECT):
    project = Path(project).resolve()
    packaged = project / 'modules'
    return packaged if packaged.is_dir() else project.parent
