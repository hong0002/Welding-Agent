"""Flat native simulator_final contract, independent of STP rollback."""
from pathlib import Path
from backend.services.simulator_stp_contract import NATIVE_FILES as STP_FILES

NATIVE_FILES=(*STP_FILES,'welding_path_marks.py','welding_command_queue.py',
    'welding_video.py','urdf_import_compat.py','viewport_capture_compat.py',
    'contact_registration_determinism.py','rb10_trajectory_with_ATU01035.usda')


def require_native_contract(root):
    from backend.services.current_preview_config import CurrentPreviewError
    root=Path(root)
    if not all((root/name).is_file() for name in NATIVE_FILES):
        raise CurrentPreviewError('SIMULATOR_FINAL_SOURCE_INVALID','Native simulator_final source/assets are missing.',503)
    text=(root/'run_rb10_trajectory_with_ATU01035.py').read_text(encoding='utf-8')
    if 'import_urdf_isaac61' not in text or 'capture_native_frame' not in text:
        raise CurrentPreviewError('SIMULATOR_FINAL_SOURCE_INVALID','Native Isaac/capture compatibility contract differs.',503)
