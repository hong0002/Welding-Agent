"""Start the persistent welding simulator; no arguments required."""
import runpy
import sys
from pathlib import Path

if __name__ == '__main__':
    if '--serve' not in sys.argv:
        sys.argv.insert(1, '--serve')
    runpy.run_path(str(Path(__file__).with_name('run_rb10_trajectory_with_ATU01035.py')),
                  run_name='__main__')
