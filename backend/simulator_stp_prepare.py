"""Fixed offline native STP bridge; no Isaac/queue/native renderer imports."""
import contextlib
import io
import json
from pathlib import Path
import sys

if __name__ == '__main__':
    sys.dont_write_bytecode = True
    project = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project))
    sys.path.insert(0, str(project/'.cache/simulator2/python-deps'))
    from backend.simulator2_prepare import main
    options = json.loads(sys.stdin.read())
    if options.get('backend') != 'dataset_stp' or options.get('layout') != 'stp':
        raise ValueError('Invalid fixed STP bridge manifest')
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        result = main(options)
    print(json.dumps(result, allow_nan=False))
