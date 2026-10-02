"""Explicit offline display replay of one current stored job. No pipeline dispatch."""
from pathlib import Path
import shutil

from backend.model_clients.config import ROOT
from backend.model_clients.native import read_json, sha256
from backend.schemas import WeldJob, WorkflowState

SOURCE_JOB = ROOT / 'backend/storage/jobs/1bcbe8ee-d689-49b9-a64f-c04562ffe5f8.json'


def install_display_replay(workflow):
    job = WeldJob.model_validate(read_json(SOURCE_JOB))
    native_id = job.mask.artifact.provenance.native_source_artifact_id
    record_path = ROOT / '.cache/native-models' / f'{native_id}.json'
    record = read_json(record_path)
    directory = Path(record['directory'])
    # All prior native artifacts remain byte-identical, including non-display output.
    assert all(sha256(directory / name) == h for name, h in record['files'].items())
    source_storage = ROOT / 'backend/storage'
    for view in job.scene.views.values():
        images = [('scenes', view.image_id, '.png')]
        if view.mask:
            images += [('masks', view.mask.id, '.png'), ('masks', view.mask.id, '.overlay.png')]
        for folder, identity, suffix in images:
            source = source_storage / folder / f'{identity}{suffix}'
            target = workflow.storage.artifact_path(folder, identity, suffix)
            if not target.exists():
                shutil.copyfile(source, target)
    shutil.copyfile(source_storage / 'native_context' / f'{job.id}.scene.json',
                   workflow.storage.artifact_path('native_context', job.id, '.scene.json'))
    # Isolate the display fixture from downstream recovery/launch APIs. The current
    # masks, scene identity, Segment2 lineage and 2D guidance remain exact copies.
    job.native_output = None
    job.rough3d = None
    job.vla_prediction = None
    job.trajectory_clarification = None
    job.state = WorkflowState.ROUGH_PATH_READY
    workflow.storage.save_job(job)
    shutil.copyfile(record_path, workflow.segmentation.runtime.records / record_path.name)
    return job
