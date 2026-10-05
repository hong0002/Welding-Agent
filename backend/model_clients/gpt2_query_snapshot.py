"""Current query I/O snapshot only; no RICL arrays, model call or finalization."""
import json
from pathlib import Path
import shutil
from uuid import uuid4

import h5py
import numpy as np

from backend.model_clients.config import ROOT
from backend.model_clients.guided_vla import GuidedVLAError
from backend.model_clients.guided_workflow import conditioning_hash
from backend.model_clients.native import CAMERAS, read_json, sha256
from backend.services.dataset_sample import exact_assets
from backend.services.gpt2_prediction_proof import FRAME
from backend.services.scene_dataset import DatasetScenes


def validate_current_query(storage, job, *, instruction=None, dataset=None):
    """Read-only production input admission; only the first H5 XYZ is read.

    Only the first H5 XYZ is read. Full query GT and any old prediction are absent.
    Native full-mode seam labels come from the current sample dataset label; web
    edited binary masks are lineage, not silently converted to native polylines.
    """
    try:
        if not job.scene.sample_id or not job.instruction:
            raise ValueError('Current sample and instruction required')
        source = read_json(storage.artifact_path('native_context',job.id,'.scene.json'))
        if source['sample_id'] != job.scene.sample_id or set(source['images']) != set(CAMERAS):
            raise ValueError('Current 9-view binding')
        binding = conditioning_hash(job)
        if conditioning_hash(storage.get_job(job.id)) != binding:
            raise ValueError('Stale job')
        resolved = (dataset or DatasetScenes(source['dataset_root'])).resolve(job.scene.sample_id)
        if resolved.sample_id != job.scene.sample_id or resolved.split != job.scene.split:
            raise ValueError('Sample/split mismatch')
        label = read_json(resolved.label)
        if label['info']['gid'] != job.scene.sample_id:
            raise ValueError('Label identity')
        for view in CAMERAS:
            image = storage.artifact_path('scenes',job.scene.views[view].image_id)
            if (sha256(source['images'][view]) != source['hashes'][view] or
                    sha256(resolved.images[view]) != source['hashes'][view] or
                    sha256(image) != source['normalized_hashes'][view]):
                raise ValueError('Scene changed')
        h5, _ = exact_assets(source['dataset_root'],job.scene.sample_id)
        with h5py.File(h5,'r') as f:
            data = f['trajectory']
            if data.ndim != 2 or data.shape[0] < 1 or data.shape[1] < 3:
                raise ValueError('H5 first XYZ missing')
            start = np.asarray(data[0,:3],dtype=float)
        if not np.isfinite(start).all():
            raise GuidedVLAError('GPT2_KNOWN_START_INVALID')
        text = instruction if instruction is not None else job.instruction.text
        if not isinstance(text,str) or not text.strip():
            raise ValueError('Instruction missing')
        return source, resolved, h5, start, text, binding
    except GuidedVLAError:
        raise
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        raise GuidedVLAError('GPT2_INPUT_INVALID') from None


def snapshot_current_query(storage, job, output_root, *, instruction=None, dataset=None, project=ROOT, stage=None):
    """Immutable query-only snapshot; no GT/baseline NPZ or inference."""
    output_root = Path(output_root).resolve()
    if not output_root.is_relative_to(Path(project).resolve()/'.cache'):
        raise GuidedVLAError('GPT2_INPUT_INVALID')
    try:
        source,resolved,h5,start,text,binding = validate_current_query(storage,job,instruction=instruction,dataset=dataset)
        label_hash = sha256(resolved.label)
        stage = Path(stage).resolve() if stage else output_root/str(uuid4())
        if stage.parent != output_root: raise ValueError('Snapshot ownership')
        query = stage/'inputs'/job.scene.sample_id
        (query/'raw_rgb').mkdir(parents=True,exist_ok=False)
        shutil.copyfile(resolved.label,query/'source_label.json')
        for view in CAMERAS:
            shutil.copyfile(source['images'][view],query/'raw_rgb'/f'{view}_Color.png')
        metadata = dict(episode_id=job.scene.sample_id,split=job.scene.split,instruction=text,
                        start_xyz=start.tolist(),source_units='mm',coordinate_frame=FRAME)
        (query/'metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,allow_nan=False),encoding='utf-8')
        if (sha256(query/'source_label.json') != label_hash or
                any(sha256(query/'raw_rgb'/f'{v}_Color.png') != source['hashes'][v] for v in CAMERAS) or
                conditioning_hash(storage.get_job(job.id)) != binding):
            raise ValueError('Inputs changed during snapshot')
        receipt = dict(schema_version=1,status='QUERY_INPUTS_STAGED_ONLY',job_id=str(job.id),
            sample_id=job.scene.sample_id,split=job.scene.split,conditioning_sha256=binding,
            query_directory=query.relative_to(stage).as_posix(),known_start_source='exact H5 trajectory[0,:3]',
            h5_sha256=sha256(h5),start_xyz_order=['X','Y','Z'],start_units='mm',
            source_label_sha256=label_hash,mask_policy='native_dataset_seam_labels',
            web_masks_used_as_input=False,query_gt_trajectory_included=False,baseline_prediction_included=False,
            trajectory_npz_created=False,native_invocations=0,model_calls=0,ssh_calls=0,
            native_cli_ready=True,prediction_only=True,
            files={p.relative_to(stage).as_posix():sha256(p) for p in query.rglob('*') if p.is_file()})
        (stage/'snapshot.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
        return stage, query, receipt
    except GuidedVLAError:
        raise
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        raise GuidedVLAError('GPT2_INPUT_INVALID') from None
