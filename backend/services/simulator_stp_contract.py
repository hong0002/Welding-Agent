"""Stdlib STP-reference environment source contract, usable before Isaac imports."""
import ast
import hashlib
from pathlib import Path
from backend.services.simulator2_contract import NATIVE_FILES as V2_FILES

NATIVE_FILES = (*V2_FILES, 'welding_environment.py', 'run_rb10_trajectory_with_ATU01035.py')
AUDIT_FILES = (*NATIVE_FILES, 'run_welding_simulator.py', 'welding_command_queue.py')


def inspect_native_contract(root):
    native = Path(root).resolve()/'simulator'
    files = {name:hashlib.sha256((native/name).read_bytes()).hexdigest()
        for name in AUDIT_FILES if (native/name).is_file()}
    layout = False
    if 'run_welding_sample.py' in files:
        tree = ast.parse((native/'run_welding_sample.py').read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            if (isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='add_argument'
                    and any(isinstance(arg,ast.Constant) and arg.value=='--layout' for arg in node.args)):
                choices = next((k.value for k in node.keywords if k.arg=='choices'),None)
                layout = isinstance(choices,(ast.Tuple,ast.List)) and 'stp' in ast.literal_eval(choices)
    complete = len(files)==len(AUDIT_FILES)
    return dict(native_layout_flag='--layout stp' if layout else None,native_files=files,
        source_complete=complete,contract_pass=complete and layout,cad_source='sample_obj',
        environment_source='stp_reference_layout',code=None if complete and layout else 'SIMULATOR_STP_SOURCE_INVALID')
