"""Reuse existing exact artifact/approval gates; replace only native authority."""
from backend.services.simulator2_gate import OWNED_CODE as V2_OWNED,verify as verify_dataset

OWNED_CODE=(*V2_OWNED,'backend/services/simulator_final_gate.py',
    'backend/services/simulator_final_contract.py','backend/services/simulator_final_client.py',
    'backend/simulator_final_prepare.py','backend/simulator_final_preview.py',
    'backend/simulator_final_experience.py','backend/services/preview_startup.py',
    'backend/services/simulator_final_result.py','backend/services/current_preview_frames.py',
    'backend/services/visibility_path_preview.py','backend/services/robot_demo.py',
    'backend/services/gpt2_simulator_companion.py','backend/services/simulator_final_live.py')


def verify(d,path,project):
    return verify_dataset(d,path,project,final=True)
