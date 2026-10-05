"""One result-view action. Scene registration is optional, robot gates independent."""
from backend.services.output_catalog import xyz_output
from backend.services.geometry_preview import GeometryPreviewService
from backend.services.current_preview_config import CurrentPreviewError
from backend.orchestrator.state_machine import WorkflowError
from backend.model_clients.guided_vla import GuidedVLAError


class ResultPathPreview:
    def __init__(self,workflow,runtime,scene_preview,*,project=None):
        self.workflow,self.runtime,self.scene_preview=workflow,runtime,scene_preview
        self.geometry=GeometryPreviewService(workflow,runtime,project=project)

    def run(self,job_id,artifact=None,stage_index=None,output_kind=None):
        job=self.workflow.get_display_job(job_id)
        try:row=xyz_output(self.workflow.storage,job,self.workflow.final_predictor,artifact,stage_index,project=self.geometry.project,output_kind=output_kind)
        except ValueError:raise CurrentPreviewError('GEOMETRY_OUTPUT_MISSING','표시할 숫자 XYZ가 없습니다.',409) from None
        result=dict(job_id=str(job.id),artifact_id=row['id'],stage_index=row.get('stage_index'),
            display=row,physical_robot_executable=False,robot_ready=False)
        if getattr(self.scene_preview,'backend',None)=='dataset_final':
            # Path-only inspection is the web source viewer. Native final main
            # owns the complete scene/playback and is never replaced by WA math.
            return dict(result,viewer_mode='WEB_SOURCE_FRAME',reason_code=None)
        accepted=job.vla_prediction
        if (accepted and str(accepted.artifact_id)==row['id'] and stage_index is None and not row['stale']
                and row.get('current_overlay_allowed') and row.get('coordinate_frame')=='source_robot_frame_unaligned_with_isaac'):
            available=False
            try:available=self.scene_preview.capabilities(job_id=job.id).get('path_preview_ready')
            except (CurrentPreviewError,WorkflowError,GuidedVLAError,OSError,ValueError):pass
            if available:
                try:
                    self.scene_preview.run(job_id=job.id,artifact_id=accepted.artifact_id,kind='path',selected_source=row)
                    return dict(result,viewer_mode='REGISTERED_SCENE',reason_code=None)
                except (CurrentPreviewError,WorkflowError,GuidedVLAError,OSError,ValueError):
                    # Never launch a second renderer after a scene launch attempt.
                    return dict(result,viewer_mode='WEB_SOURCE_FRAME',reason_code='SIMULATOR_UNAVAILABLE_WEB_VIEW_AVAILABLE')
        mode='RELATIVE_FRAME' if 'relative' in row.get('coordinate_frame','') else 'SOURCE_FRAME'
        try:
            self.runtime.check_configuration(kind='path')
            claim=self.geometry.prepare_display(job.id,row['id'],row.get('stage_index'),row['stage'])
            self.runtime.submit(claim)
            return dict(result,viewer_mode=mode,reason_code=None)
        except (CurrentPreviewError,WorkflowError,GuidedVLAError,OSError,ValueError):
            # The web projection already has exact finite runs. Runtime admission
            # failure cannot remove result access or masquerade as robot readiness.
            return dict(result,viewer_mode='WEB_SOURCE_FRAME',reason_code='SIMULATOR_UNAVAILABLE_WEB_VIEW_AVAILABLE')
