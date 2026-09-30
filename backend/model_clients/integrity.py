"""Standard-library-only external source fingerprinting, usable in either model environment."""
import hashlib
from pathlib import Path


def source_digest(repository: Path):
    files = sorted([*repository.glob("*.py"), *repository.glob("requirements*.txt"), *repository.glob("config/*.yaml")])
    return hashlib.sha256("".join(str(p.relative_to(repository)) + hashlib.sha256(p.read_bytes()).hexdigest() for p in files).encode()).hexdigest()
