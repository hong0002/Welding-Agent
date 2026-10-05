"""Camera-specific visualization inputs; never approve masks or create pixels."""
import re
from pathlib import Path
from PIL import Image
import numpy as np
from backend.model_clients.native import CAMERAS, read_json, sha256
from backend.model_clients.guided_vla import GuidedVLAError, resolve_split
from backend.model_clients.native import NativeBinding
from backend.services.mask_service import validate_binary_mask

VIEWS = ('F', 'R', 'S4')


def selected_views(message):
    # A semantic camera selection, not a pixel operation. None means available all.
    if re.search(r'전부|모두|전체|all\s+mask', message, re.I): return None
    found = re.findall(r'(?<![A-Za-z0-9])(S4|F|R)(?![A-Za-z0-9])', message.upper())
    return [v for v in VIEWS if v in found] or None


def inputs(storage, job, requested=None):
    try:
        if not job.scene or set(job.scene.views)!=set(CAMERAS): raise ValueError()
        source=read_json(storage.artifact_path('native_context',job.id,'.scene.json'))
        if set(source['images'])!=set(CAMERAS): raise ValueError()
        for v in CAMERAS:
            if sha256(source['images'][v])!=source['hashes'][v]: raise ValueError()
            if sha256(storage.artifact_path('scenes',job.scene.views[v].image_id))!=source['normalized_hashes'][v]: raise ValueError()
        if requested is not None and (not requested or len(set(requested))!=len(requested) or any(v not in VIEWS for v in requested)): raise ValueError()
        available={}
        for v in VIEWS:
            if requested is not None and v not in requested:continue
            mask=job.mask if v=='F' and job.mask else job.scene.views[v].mask
            path=None;flags=[];identity=None;approved_at=None
            if mask:
                if mask.scene_id not in (job.scene.id,job.scene.views[v].image_id) or (mask.view_id and mask.view_id!=v): raise ValueError()
                path=storage.artifact_path('masks',mask.id);identity=str(mask.id)
                flags=['APPROVED' if mask.approved else 'UNAPPROVED']
                if mask.mask_source in ('manual','manual_edited'):flags.append('MANUAL')
                if mask.mask_source=='ai_refined':flags.append('REFINED')
                approved_at=mask.approved_at.isoformat() if mask.approved_at else None
            elif job.raw_segment_output:
                from backend.model_clients.model_display import verified
                try:display,folder=verified(storage,job,job.raw_segment_output,'segment')
                except (OSError,ValueError,KeyError,TypeError,AttributeError):continue
                if display.sample_id==job.scene.sample_id and display.overlay_allowed and v in display.mask_urls:
                    path=folder/f'{v}.png';identity=str(job.raw_segment_output.native_artifact_id)
                    flags=['UNAPPROVED','RAW']
            if path:
                try:
                    with Image.open(path) as im:
                        validate_binary_mask(im,(job.scene.views[v].width,job.scene.views[v].height))
                        if not np.any(np.asarray(im)): continue
                except (OSError,ValueError):continue
                available[v]=dict(path=str(Path(path).resolve()),id=identity,sha256=sha256(path),provenance=flags,approved_at=approved_at)
        chosen=[v for v in VIEWS if v in (requested if requested is not None else available)]
        if not chosen or any(v not in available for v in chosen):
            raise GuidedVLAError('GPT_MASK_VIEW_UNAVAILABLE')
        split=resolve_split(source['dataset_root'],NativeBinding(sample_id=job.scene.sample_id,camera='F',image=Path(source['images']['F'])))
        if split['split']!=job.scene.split:raise ValueError()
        return source,split,{v:available[v] for v in chosen}
    except GuidedVLAError:raise
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        raise GuidedVLAError('GPT_MASK_CONDITIONING_INVALID') from None
