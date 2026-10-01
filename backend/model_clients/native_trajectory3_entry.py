"""Fixed import bridge for trajectory3's historical ../vlm_project dependency.

Load the actual native Segment2 detector unchanged under the alias that native
yolo_client already recognizes, then execute native cot.py. No detector logic,
model prompts or trajectory generation is implemented here.
"""
import importlib.util
from pathlib import Path
import runpy
import sys


def install_detector(segment2):
    name = 'welding_shared_yolo_client'
    if name in sys.modules:
        raise ValueError('Detector module already installed')
    spec = importlib.util.spec_from_file_location(name, segment2/'retrieval_client.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    if not callable(getattr(module, 'detect_images', None)) or not hasattr(module, 'RetrievalConfig'):
        raise ValueError('Native detector contract unavailable')
    sys.path.append(str(segment2))  # detect_images imports native mask_data lazily.
    return module


def main():
    project = Path(__file__).resolve().parents[2]
    trajectory3 = project.parent/'vlm_trajectory3'
    segment2 = project.parent/'vlm_segment2'
    if Path.cwd().resolve() != trajectory3.resolve():
        raise ValueError('Fixed native trajectory3 cwd required')
    install_detector(segment2)
    sys.path.insert(0, str(trajectory3))
    sys.argv[0] = str(trajectory3/'cot.py')
    runpy.run_path(sys.argv[0], run_name='__main__')


if __name__ == '__main__':
    main()
