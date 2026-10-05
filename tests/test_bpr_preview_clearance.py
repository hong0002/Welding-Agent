"""The preview torch policy must not execute for any other dataset sample."""
from pathlib import Path
import pytest
from backend.simulator_final_prepare import bpr_tool_clearance


@pytest.mark.parametrize('sample',['B_PR_03_0002','B_PR_03_0004','B_PP_03_0001','T_PR_03_0007'])
def test_other_samples_are_untouched_without_native_imports(tmp_path,sample):
    solution=tmp_path/'trajectory_solution.npz'
    solution.write_bytes(b'unchanged native fixture')
    report={'original':'unchanged'}
    assert bpr_tool_clearance(solution,report,tmp_path/'absent-native-project',sample) is None
    assert solution.read_bytes()==b'unchanged native fixture' and report=={'original':'unchanged'}
    assert list(tmp_path.iterdir())==[solution]
