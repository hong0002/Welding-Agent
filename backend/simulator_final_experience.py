"""Owned Isaac app profile: keep native playback, exclude unused broken RTX sensors.

Installed experience files are read only. No renderer/physics/camera settings are
changed; the native SimulationApp launch config is passed through unchanged.
"""
from pathlib import Path


EXCLUDED = ('isaacsim.sensors.experimental.rtx', 'isaacsim.sensors.rtx')


def build_experience(isaac_root: Path, output: Path) -> Path:
    apps = isaac_root / 'apps'
    base = (apps / 'isaacsim.exp.base.kit').read_text(encoding='utf-8')
    python = (apps / 'isaacsim.exp.base.python.kit').read_text(encoding='utf-8')
    for name in EXCLUDED:
        declaration = f'"{name}" = {{}}'
        if base.count(declaration) != 1:
            raise ValueError('Unexpected installed Isaac base dependency contract')
        base = base.replace(declaration, '# Unused RTX sensor excluded from welding playback')
    output.mkdir(parents=True, exist_ok=True)
    # ${app} would otherwise refer to this owned profile directory.
    base = base.replace('${app}', apps.as_posix())
    python = python.replace('"isaacsim.exp.base" = {}', '"weld.exp.base" = {}')
    python = python.replace('"${app}",', f'"{output.resolve().as_posix()}",\n    "{apps.as_posix()}",')
    python = python.replace('${app}', apps.as_posix())
    (output / 'weld.exp.base.kit').write_text(base, encoding='utf-8')
    path = output / 'weld.exp.python.kit'
    path.write_text(python, encoding='utf-8')
    return path


def bind_experience(experience: Path) -> None:
    """Select fixed owned startup profile before original native renderer import."""
    import isaacsim
    original = isaacsim.SimulationApp

    def native_app(launch_config=None, **kwargs):
        if kwargs:
            raise ValueError('Unexpected native SimulationApp arguments')
        return original(launch_config, experience=str(experience))

    isaacsim.SimulationApp = native_app
