"""Read-only Current Preview gate, independent of existing sample replay settings."""
import os
from pathlib import Path
import xml.etree.ElementTree as ET

from backend.orchestrator.state_machine import WorkflowError
from backend.services.simulator_process import batch_command
from backend.services.simulator_prediction_package import PROJECT, SIMULATOR_FILES

GEOMETRY = PROJECT / '.cache/bpr-geometry-audit/0efd49b0-a360-466e-b7f1-2fe5cdee0d2e/diagnostics.json'
CLEARANCE = PROJECT / '.cache/bpr-tool-clearance/a74cb77c-7d4e-4617-b20d-57a43fcb89cf/summary.json'


class CurrentPreviewError(WorkflowError):
    def __init__(self, code, message, status_code=503):
        self.code = code
        super().__init__(message, status_code)


def configuration(config, *, geometry=GEOMETRY, clearance=CLEARANCE, kind='robot'):
    """Static capability only. The current job/package is checked on every POST.

    No sample_id, replay data_root, samples_dir or prediction_root is consulted.
    No subprocess, USD import, inference, lease or queue is created here.
    Exact sample placement evidence belongs to the requested family policy.
    """
    issues = []
    def issue(code, message):
        issues.append(dict(code=code, message=message))
    executable = config.executable
    if executable is None or not executable.is_file():
        issue('CURRENT_PREVIEW_LAUNCHER_NOT_CONFIGURED', 'Current Preview requires the configured Isaac launcher (WELD_SIM_LAUNCHER).')
    elif os.name == 'nt':
        try:
            if executable.suffix.lower() not in {'.exe', '.bat', '.cmd'}:
                raise ValueError()
            if executable.suffix.lower() in {'.bat', '.cmd'}:
                batch_command(executable, PROJECT / 'backend/simulator_runner.py')
        except ValueError:
            issue('CURRENT_PREVIEW_LAUNCHER_INVALID', 'Current Preview launcher type or batch path is invalid.')
    if config.configuration_error:
        issue('CURRENT_PREVIEW_CONFIGURATION_INVALID', config.configuration_error)
    if config.runtime_dir.resolve().is_relative_to(config.root.resolve()):
        issue('CURRENT_PREVIEW_CONFIGURATION_INVALID', 'Current Preview outputs must remain outside the read-only simulator source.')
    missing = [name for name in SIMULATOR_FILES if not (config.root / name).is_file()] if kind == 'robot' else []
    if not config.root.is_dir():
        issue('CURRENT_PREVIEW_ASSET_MISSING', 'Configured simulator source directory is missing.')
    if missing:
        issue('CURRENT_PREVIEW_ASSET_MISSING', 'Missing audited simulator source/assets: ' + ', '.join(missing))
    elif kind == 'robot':
        try:
            tree = ET.parse(config.root / 'rbpodo_description/robots/rb10_1300e_u.urdf')
            for mesh in tree.findall('.//mesh'):
                name = mesh.attrib['filename']
                if not name.startswith('package://rbpodo_description/'):
                    raise ValueError()
                path = (config.root / name.removeprefix('package://')).resolve()
                if not path.is_relative_to(config.root.resolve()) or not path.is_file():
                    raise ValueError()
        except (OSError, ValueError, KeyError, ET.ParseError):
            issue('CURRENT_PREVIEW_ASSET_MISSING', 'Audited URDF mesh assets are missing or invalid.')
    return dict(configured=not issues, configuration_errors=[i['message'] for i in issues],
        configuration_codes=[i['code'] for i in issues],
        request_requirements=['current_job', 'current_vla_artifact', 'immutable_current_prediction_package'],
        configuration_scope='current_preview_'+kind+'_runtime', kind=kind)


def require_configuration(config, **kwargs):
    status = configuration(config, **kwargs)
    if not status['configured']:
        raise CurrentPreviewError(status['configuration_codes'][0], status['configuration_errors'][0])
