"""Safe current/previous model output viewers, separate from workflow admission."""
from uuid import UUID
from backend.schemas import NativeOutputReport
from backend.model_clients.model_display import verified
from backend.model_clients.geometry_display import presentation
from backend.model_clients.guided_vla import GuidedVLAError


def native_output(job,artifact):
    for stage,report in (('segment',job.raw_segment_output),('trajectory',job.native_output)):
        if report and report.native_artifact_id==artifact:return stage,report,False
    for entry in job.previous_outputs:
        if entry['stage'] in ('segment','trajectory') and entry['id']==str(artifact):
            return entry['stage'],NativeOutputReport.model_validate(entry['output']),True
    raise ValueError('DISPLAY_OUTPUT_NOT_FOUND')


def image(storage,job,artifact,view):
    stage,report,_=native_output(job,artifact)
    display,folder=verified(storage,job,report,stage)
    if view not in display.mask_urls:raise ValueError('DISPLAY_OUTPUT_NOT_FOUND')
    return folder/f'{view}.png'


def catalog(storage,job,final_client,*,project=None):
    rows=[]
    entries=[dict(stage=stage,id=str(report.native_artifact_id),output=report.model_dump(mode='json'),stale=False)
        for stage,report in (('segment',job.raw_segment_output),('trajectory',job.native_output))
        if report and report.native_artifact_id]
    entries += [dict(v,stale=True) for v in job.previous_outputs if v['stage'] in ('segment','trajectory')]
    for entry in entries:
        report=NativeOutputReport.model_validate(entry['output'])
        try:d,_=verified(storage,job,report,entry['stage'])
        except (OSError,ValueError,TypeError,KeyError):
            rows.append(dict(id=entry['id'],stage=entry['stage'],label='Model output',stale=entry['stale'],
                states=presentation(exists=True,renderable=False),warnings=['DISPLAY_EVIDENCE_INVALID']))
            continue
        refined='refinement' in report.artifacts
        # Refinement source is explicit native report metadata when available.
        refined=refined or bool(job.mask and job.mask.mask_source=='ai_refined' and
            job.mask.artifact and job.mask.artifact.provenance.native_source_artifact_id==report.native_artifact_id)
        rows.append(dict(id=entry['id'],stage=entry['stage'],
            label='AI Refined from Manual' if refined else 'AI Segment2 Raw' if entry['stage']=='segment' else 'Trajectory3 Raw',
            stale=entry['stale'],sample_id=d.sample_id,current_overlay_allowed=d.overlay_allowed and not entry['stale'],
            states=presentation(exists=d.available,renderable=d.displayable,
                validated=report.validation.status=='PASS',approved=False,stale=entry['stale']),warnings=d.warnings,
            segments=[v.model_dump(mode='json') for v in d.segments],width=d.width,height=d.height,
            mask_urls={v:f'/api/weld/{job.id}/model-output/artifacts/{entry["id"]}/{v}/image' for v in d.mask_urls}))
    masks=[(job.mask,False)] if job.mask else []
    masks += [(v.mask,False) for v in job.scene.views.values() if v.mask and (not job.mask or v.mask.id!=job.mask.id)]
    from backend.schemas import Mask
    masks += [(Mask.model_validate(v['output']),True) for v in job.previous_outputs if v['stage']=='mask']
    for mask,stale in masks:
        rows.append(dict(id=str(mask.id),stage='mask',label='Approved Mask' if mask.approved else
            'Manual Edited' if mask.mask_source in ('manual','manual_edited') else 'AI Refined from Manual' if mask.mask_source=='ai_refined' else 'Mask Draft',
            stale=stale,sample_id=job.scene.sample_id,current_overlay_allowed=not stale,
            states=presentation(exists=True,renderable=True,validated=True,approved=mask.approved,stale=stale),
            mask_urls={mask.view_id or 'F':mask.image_url},warnings=[]))
    finals=[(job.raw_final_prediction,False)] if job.raw_final_prediction else []
    from backend.schemas import FinalPredictionDisplay
    finals += [(FinalPredictionDisplay.model_validate(v['output']),True) for v in job.previous_outputs if v['stage']=='final']
    for d,stale in finals:
        try:
            if hasattr(final_client,'read_display') and final_client.status().get('source')==d.source:value=final_client.read_display(storage,job,d.artifact_id)
            else:
                from backend.services.visibility_artifacts import gpt_display
                from backend.model_clients.config import ROOT
                value=gpt_display(job,d,project=project or ROOT)
        except (OSError,ValueError,KeyError,TypeError,GuidedVLAError,AttributeError):value=None
        selected=next((s for s in reversed(value.get('stages',[])) if s.get('runs')), {}) if value else {}
        source_label=selected.get('stage','GPT Final / Raw')
        if not source_label.startswith('GPT'):source_label='GPT · '+source_label
        rows.append(dict(id=str(d.artifact_id),stage='final',source=d.source,label=source_label,stale=stale or bool(value and value.get('stale')),
            sample_id=selected.get('sample_id',job.scene.sample_id),current_overlay_allowed=bool(value and value.get('current_overlay_allowed')),
            states=presentation(exists=True,renderable=bool(value and any(v.get('runs') for v in value.get('stages',[])) or value and value.get('runs')),
                validated=d.validation_status=='PASS',approved=False,
                simulation=bool(value),stale=stale or bool(value and value.get('stale'))),
            dimensions=3,runs=value.get('runs',[]) if value else [],coordinate_frame=d.coordinate_frame,units=d.units,
            display_url=d.display_url,warnings=[] if value else ['DISPLAY_EVIDENCE_INVALID']))
        for index,stage in enumerate(value.get('stages',[]) if value else []):
            rows.append(dict(id=str(d.artifact_id),stage='gpt_stage',source=d.source,stage_index=index,label=stage['stage'],dimensions=3,
                stale=stale or bool(value.get('stale')),sample_id=stage.get('sample_id',job.scene.sample_id),
                current_overlay_allowed=not stale and not value.get('stale') and stage.get('current_overlay_allowed',True),
                states=presentation(exists=True,renderable=bool(stage['runs']),simulation=bool(stage['runs']),stale=stale or bool(value.get('stale'))),
                runs=stage['runs'],coordinate_frame=stage['coordinate_frame'],units=stage['units'],warnings=[]))
    from backend.services.visibility_artifacts import prediction_rows,simulator_rows,recovered_gpt_rows
    from backend.orchestrator.state_machine import StateMachine
    from backend.model_clients.geometry_display import finite_runs
    previews=[dict(stage=stage,id=StateMachine.preview_identity(job,stage,p.model_dump(mode='json')),output=p.model_dump(mode='json'),stale=False)
        for stage,p in [('rough_preview',job.rough_trajectory),('final_preview',job.final_trajectory)] if p]
    previews += [dict(v,stale=True) for v in job.previous_outputs if v['stage'] in ('rough_preview','final_preview')]
    for entry in previews:
        segments=[dict(segment_id=s['segment_id'],region_id=s['region_id'],runs=finite_runs(
            [[p['x'],p['y']] for p in s['points']],2)[0]) for s in entry['output']['segments']]
        rows.append(dict(id=entry['id'],stage=entry['stage'],label='Rough 2D Preview' if entry['stage']=='rough_preview' else 'Final 2D Preview',
            stale=entry['stale'],dimensions=2,sample_id=entry.get('sample_id',job.scene.sample_id),current_overlay_allowed=not entry['stale'],
            segments=segments,states=presentation(exists=True,renderable=any(s['runs'] for s in segments),
                validated=not entry['stale'] and (entry['stage']=='rough_preview' or bool(job.validation and job.validation.valid)),stale=entry['stale']),warnings=[]))
    from backend.model_clients.config import ROOT
    root=project or ROOT
    rows+=recovered_gpt_rows(job,{r['id'] for r in rows if r['stage']=='final' and r['states']['OUTPUT_RENDERABLE']},project=root)
    rows+=prediction_rows(storage,job,project=root)+simulator_rows(job,project=root)
    if job.latest_final_attempt:
        attempt_id=job.latest_final_attempt.get('attempt_id') or str(job.id)
        rows=[r for r in rows if not (r['stage']=='attempt' and r['id']==attempt_id)]
        rows.append(dict(id=attempt_id,stage='attempt',label='NEW GPT OUTPUT · '+job.latest_final_attempt['status'],
            stale=False,states=presentation(exists=True,renderable=False),warnings=[job.latest_final_attempt.get('error_code') or 'FINAL_STAGE_STATUS'],
            model_stages=job.latest_final_attempt.get('stages',[])))
    return dict(job_id=str(job.id),outputs=rows)


def xyz_output(storage,job,final_client,artifact=None,stage_index=None,*,project=None,output_kind=None):
    rows=catalog(storage,job,final_client,project=project)['outputs']
    options=[r for r in rows if r.get('dimensions')==3 and r['states']['OUTPUT_RENDERABLE'] and r.get('runs')]
    if artifact:
        options=[r for r in options if r['id']==str(artifact) and (r.get('stage_index')==stage_index if stage_index is not None else r['stage']!='gpt_stage')]
    if output_kind:options=[r for r in options if r['stage']==output_kind]
    if not options:raise ValueError('DISPLAY_GEOMETRY_MISSING')
    if artifact is None:
        # Current raw GPT takes precedence over an older accepted predictor or
        # saved simulator playback. Explicit selections remain exact.
        for kind in ('final','prediction','gpt_stage'):
            current=[r for r in options if not r['stale'] and r['stage']==kind]
            if current:return current[-1]
    return next((r for r in reversed(options) if not r['stale']),options[-1])
