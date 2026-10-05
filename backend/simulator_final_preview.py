"""Execute original native main in an owned snapshot; observe, never rebuild scene."""
import os
from pathlib import Path
import runpy
import shutil
import sys

from backend.services.current_preview_gate import read,resolve_command,sha
from backend.simulator_final_experience import build_experience,bind_experience


def main(options):
    session=Path(options['session']).resolve();request=options['first_request']
    descriptor,_,_=resolve_command(read(session/'queue'/(request+'.json')),read(session/'catalog.json'))
    if descriptor.get('backend')!='dataset_final' or descriptor['kind']!='robot':raise ValueError('Wrong native final claim')
    output=session/'outputs'/request;output.mkdir(parents=True,exist_ok=False)
    native=session/'native';native.mkdir(exist_ok=False)
    package=Path(descriptor['package']);provenance=read(package)['provenance'];root=Path(descriptor['simulator_root'])
    for name,digest in provenance['simulator_files'].items():
        destination=native/name;destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(root/name,destination)
        if sha(destination)!=digest:raise ValueError('Native snapshot changed')
    sys.path.insert(0,str(native))
    project=Path(__file__).resolve().parents[1]
    sys.path.insert(1,str(project/'.cache/simulator2/python-deps'))
    os.environ['WELD_SIM_URDF_OUTPUT_DIR']=str(session/'urdf')
    # Installed launcher is backend-owned, not a browser parameter.
    isaac_root=Path(os.environ['ISAAC_PATH']).resolve()
    bind_experience(build_experience(isaac_root,session/'experience'))
    import viewport_capture_compat as capture
    from backend.services.simulator_final_live import NativeLiveCapture
    live = NativeLiveCapture(output,dict(job_id=descriptor['job_id'],artifact_id=descriptor['artifact_id'],
        session_id=session.name,request_id=request),session/'stop.json')
    original_capture=capture.capture_native_frame
    def bound_capture(app,path):
        if Path(path).stem=='end': live.close()
        result=original_capture(app,path)
        if Path(path).stem=='start':
            live.start(app)
            print('[CURRENT_PREVIEW] READY '+session.name,flush=True)
        return result
    capture.capture_native_frame=bound_capture
    entry=native/'run_rb10_trajectory_with_ATU01035.py'
    sys.argv=[str(entry),'--solution',str(package.parent/'native/trajectory_solution.npz'),
        '--output',str(output/'scene.usda'),'--duration-sec','15','--camera-distance-scale','1',
        '--capture-dir',str(output),'--no-video']
    # Keep the original native GUI open at the final pose until owned stop.
    # SimulationApp replaces sys.stdout. Completion is observed from the owned
    # OS pipe by the parent, then checked against actual saved motion/captures.
    try: runpy.run_path(str(entry),run_name='__main__')
    finally: live.close()
