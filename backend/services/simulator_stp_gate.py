"""Stdlib immutable STP-layout admission before GUI imports; no fallback."""
from backend.services.simulator2_gate import OWNED_CODE as V2_OWNED, verify as verify_dataset

OWNED_CODE = (*V2_OWNED, 'backend/services/simulator_stp_gate.py',
    'backend/services/simulator_stp_contract.py', 'backend/services/simulator_stp_client.py',
    'backend/simulator_stp_prepare.py', 'backend/services/preview_environment.py')


def verify(d, path, project):
    return verify_dataset(d,path,project,stp=True)
