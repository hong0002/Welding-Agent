from uuid import UUID, uuid4
import time
import json
from pathlib import Path

from backend.model_clients.contracts import ModelArtifact, ModelFault, Provenance
from backend.model_clients.workflow_contracts import Rough3DClient, GuidedWorkflowClient
from backend.model_clients.final_trajectory import FinalTrajectoryPredictor

from backend.orchestrator.instruction_parser import DummyInstructionParser, InstructionParser
from backend.orchestrator.region_selection import resolve_regions
from backend.orchestrator.state_machine import StateMachine, WorkflowError
from backend.schemas import (Instruction, Mask, RegionSelection, Scene, SceneView, Rough3DArtifact,
    VLAResultSummary, StateEvent, StructuredInstruction, WeldJob, WorkflowState, utc_now,
    NativeOutputReport, NativeCandidateValidation)
from backend.services.components import DEFAULT_MIN_COMPONENT_AREA, detect_components
from backend.services.isaac_client import DisabledIsaacClient, IsaacClient
from backend.services.mask_service import create_mask_overlay, decode_image, validate_binary_mask
from backend.services.rough_path_client import DummyRoughPathClient, RoughPathClient
from backend.services.segmentation_client import DummySegmentationClient, SegmentationClient
from backend.services.storage import LocalStorage
from backend.services.validation import DummyTrajectoryValidator, TrajectoryValidator
from backend.services.vla_client import DummyVLAClient, VLAClient


class Workflow:
    def __init__(
        self, storage: LocalStorage, *, parser: InstructionParser | None = None,
        segmentation: SegmentationClient | None = None, rough: RoughPathClient | None = None,
        vla: VLAClient | None = None, validator: TrajectoryValidator | None = None,
        isaac: IsaacClient | None = None,
        dataset=None, rough3d: Rough3DClient | None = None, guided_vla: GuidedWorkflowClient | None = None,
        final_predictor: FinalTrajectoryPredictor | None = None,
        min_component_area: int = DEFAULT_MIN_COMPONENT_AREA,
    ):
        if min_component_area < 1:
            raise ValueError("min_component_area must be at least 1.")
        self.min_component_area = min_component_area
        self.storage = storage
        self.parser = parser or DummyInstructionParser()
        self.segmentation = segmentation or DummySegmentationClient()
        self.rough = rough or DummyRoughPathClient()
        self.vla = vla or DummyVLAClient()
        self.validator = validator or DummyTrajectoryValidator()
        self.isaac = isaac or DisabledIsaacClient()
        if dataset is None:
            from backend.services.scene_dataset import DatasetScenes
            dataset=DatasetScenes.configured()
        self.dataset=dataset
        self.rough3d=rough3d
        self.guided_vla=final_predictor or guided_vla

    def upload_scene(self, data: bytes, filename: str | None = None) -> WeldJob:
        resolved=self.dataset.from_upload(data,filename) if filename else None
        if resolved:return self._load_image_set(resolved)
        image = decode_image(data)
        scene_id = uuid4()
        job = WeldJob(id=uuid4(), history=[StateEvent(state=WorkflowState.EMPTY, reason="created")])
        job.scene = Scene(id=scene_id, width=image.width, height=image.height, image_url=f"/api/scenes/{scene_id}/image")
        job.scene.artifact = ModelArtifact(kind="scene", provenance=Provenance(
            model_name="scene-upload", model_version="normalized-rgb-v1", latency_ms=0,
            reference_mode="dummy", source_scene_id=scene_id))
        with self.storage.lock:
            self.storage.save_image("scenes", scene_id, image)
            StateMachine.advance(job, WorkflowState.SCENE_READY)
            self.storage.save_job(job)
        return job

    def load_sample(self,sample_id):
        return self._load_image_set(self.dataset.resolve(sample_id))

    def _load_image_set(self,resolved):
        from backend.model_clients.native import CAMERAS,sha256
        primary=uuid4();job=WeldJob(id=uuid4(),rough_mode="native_3d")
        images={v:decode_image(p.read_bytes()) for v,p in resolved.images.items()}
        scene=Scene(id=primary,width=images['F'].width,height=images['F'].height,
            image_url=f'/api/scenes/{primary}/image',sample_id=resolved.sample_id,
            split=resolved.split,primary_view='F')
        with self.storage.lock:
            for view in CAMERAS:
                image_id=primary if view=='F' else uuid4();image=images[view]
                self.storage.save_image('scenes',image_id,image)
                scene.views[view]=SceneView(view_id=view,image_id=image_id,image_url=f'/api/scenes/{image_id}/image',
                    width=image.width,height=image.height,image_sha256=sha256(resolved.images[view]))
            job.scene=scene
            self.storage._write_json(self.storage.artifact_path('native_context',job.id,'.scene.json'),json.dumps(
                {'sample_id':resolved.sample_id,'dataset_root':str(self.dataset.root),
                 'images':{v:str(p) for v,p in resolved.images.items()},
                 'hashes':{v:scene.views[v].image_sha256 for v in CAMERAS},
                 'normalized_hashes':{v:sha256(self.storage.artifact_path('scenes',scene.views[v].image_id)) for v in CAMERAS}},ensure_ascii=False))
            StateMachine.advance(job,WorkflowState.SCENE_READY);self._save(job)
        return job

    def _scene_image(self,job,view_id=None):
        from backend.model_clients.native import NativeBinding,read_json,sha256
        view=job.scene.views.get(view_id or job.scene.primary_view) if job.scene.views else None
        image=self.storage.read_image('scenes',view.image_id if view else job.scene.id)
        if view:
            proof=read_json(self.storage.artifact_path('native_context',job.id,'.scene.json'))
            source=Path(proof['images'][view.view_id])
            if (sha256(source)!=proof['hashes'][view.view_id] or
                sha256(self.storage.artifact_path('scenes',view.image_id))!=proof['normalized_hashes'][view.view_id]):
                raise ModelFault('NATIVE_INPUT_MISMATCH')
            image.info['native_binding']=NativeBinding(sample_id=job.scene.sample_id,camera=view.view_id,image=source)
        return image

    def set_mask(self, job_id: UUID, data: bytes | None = None, *, min_component_area: int | None = None,
                 instruction: str = "용접할 영역을 찾아주세요.", edited_from_mask_id: UUID | None = None,
                 view_id: str | None = None, edited_from_raw_output_id: UUID | None = None,
                 require_review: bool = False) -> WeldJob:
        with self.storage.lock:
            job = self.storage.get_job(job_id)
            StateMachine.require(job, *StateMachine.sequence[1:],WorkflowState.VLA_READY)
            if job.scene is None:
                raise WorkflowError("A scene is required.", 409)
            view_id=view_id or job.scene.primary_view
            if view_id is not None and view_id not in job.scene.views:raise WorkflowError('Unknown scene view.',409)
            if data is None and job.scene.views and hasattr(self.segmentation,'segment_views'):
                runtime=getattr(self.segmentation,'runtime',None)
                if runtime is not None:runtime.last_display_capture=None
                if hasattr(self.segmentation,'last_result'):self.segmentation.last_result=None
                try:
                    masks=self.segmentation.segment_views(self._scene_image(job,'F'),instruction=instruction)
                    if 'F' not in masks or any(v not in job.scene.views for v in masks):raise ModelFault('MODEL_OUTPUT_INVALID')
                    # Validate every view before changing the accepted-mask slot.
                    for v,m in masks.items():
                        validate_binary_mask(m,(job.scene.views[v].width,job.scene.views[v].height))
                        if not detect_components(m,min_component_area or self.min_component_area).regions:raise ModelFault('MODEL_OUTPUT_INVALID')
                except (ModelFault,WorkflowError,OSError,ValueError):
                    self._segment_output(job,False)
                    self._save(job)
                    raise ModelFault('MODEL_OUTPUT_INVALID') from None
                self._segment_output(job,True)
                for v,m in masks.items():
                    job.scene.views[v].mask=self._store_mask(job,self._scene_image(job,v),m,
                        job.scene.views[v].mask,v,min_component_area,None,False)
                job.mask=job.scene.views['F'].mask
                StateMachine.replace_mask(job);self._save(job);return job
            previous=job.scene.views[view_id].mask if view_id else job.mask
            if edited_from_raw_output_id is not None:
                from backend.model_clients.model_display import verified
                try:
                    raw=job.raw_segment_output
                    display,_=verified(self.storage,job,raw,'segment')
                    if (data is None or raw.native_artifact_id!=edited_from_raw_output_id
                            or not display.overlay_allowed or view_id not in display.mask_urls):raise ValueError()
                except (AttributeError,OSError,ValueError,KeyError,TypeError):
                    raise WorkflowError('Raw 모델 출력이 변경되었습니다. 현재 출력을 다시 확인하세요.',409) from None
            image = self._scene_image(job,view_id)
            if edited_from_mask_id is not None and (data is None or previous is None or previous.id != edited_from_mask_id):
                raise WorkflowError("The edited mask base has changed. Reload the current mask.", 409)
            mask = decode_image(data, mask=True) if data is not None else self.segmentation.segment(image, instruction=instruction)
            metadata=self._store_mask(job,image,mask,previous,view_id,min_component_area,edited_from_mask_id,data is not None)
            if require_review:
                metadata.approved=False;metadata.approved_at=None
                self.storage._write_json(self.storage.artifact_path('masks',metadata.id,'.json'),metadata.model_dump_json(indent=2))
            if edited_from_raw_output_id is not None:
                metadata.mask_source='manual_edited'
                metadata.artifact.provenance.native_source_artifact_id=edited_from_raw_output_id
                self.storage._write_json(self.storage.artifact_path('masks',metadata.id,'.json'),metadata.model_dump_json(indent=2))
            if view_id:job.scene.views[view_id].mask=metadata
            if not view_id or view_id==job.scene.primary_view:job.mask=metadata
            StateMachine.replace_mask(job)
            self._save(job)
            return job

    def _segment_output(self,job,valid):
        from backend.model_clients.model_display import seal
        from backend.model_clients.native_candidate import issue
        result=getattr(self.segmentation,'last_result',None)
        capture=getattr(getattr(self.segmentation,'runtime',None),'last_display_capture',None)
        if result is not None:
            directory=result.directory;artifact_id=result.artifact_id
        elif capture and capture['sample_id']==job.scene.sample_id:
            directory=Path(capture['directory']);artifact_id=capture['artifact_id']
        else:
            job.raw_segment_output=NativeOutputReport(status='NATIVE_OUTPUT_MISSING',native_output_generated=False,
                validation=NativeCandidateValidation(status='FAIL',issues=[issue('segment_contract')]))
            return
        output=NativeOutputReport(status='NATIVE_OUTPUT_VALIDATED' if valid else 'NATIVE_OUTPUT_READY_UNVALIDATED',
            native_output_generated=True,native_artifact_id=artifact_id,
            validation=NativeCandidateValidation(status='PASS' if valid else 'FAIL',issues=[] if valid else [issue('segment_contract')]))
        seal(self.storage,job,output,directory,'segment')
        output.native_output_generated=bool(output.model_output.available)
        job.raw_segment_output=output

    def _store_mask(self,job,image,mask,previous,view_id,min_component_area,edited_from_mask_id,manual):
        started=time.monotonic()
        selected = validate_binary_mask(mask, image.size)
        threshold = self.min_component_area if min_component_area is None else min_component_area
        if threshold < 1:
            raise WorkflowError("min_component_area must be at least 1.")
        components = detect_components(mask, threshold)
        if not components.regions:
            raise WorkflowError(f"No welding regions remain after filtering components smaller than {threshold} pixels.")
        overlay = create_mask_overlay(image, mask)
        mask_id = uuid4()
        model_provenance = mask.info.get("model_provenance")
        edited = manual and edited_from_mask_id is not None
        source = "manual_edited" if edited else "manual" if manual else "vlm_segment" if model_provenance else "automatic"
        provenance = model_provenance or Provenance(
            model_name="manual-mask" if manual else "dummy-segmentation",
            model_version="binary-mask-v1", latency_ms=(time.monotonic() - started) * 1000,
            reference_mode="dummy", source_mask_id=edited_from_mask_id)
        provenance.source_scene_id = job.scene.id
        if model_provenance is not None and previous is not None:
            provenance.source_mask_id = previous.id  # Explicit re-detection lineage; retain prior artifacts.
        provenance.region_ids = [r.region_id for r in components.regions]
        if edited and previous.artifact:
            original=previous.artifact.provenance
            provenance.native_source_artifact_id = original.native_source_artifact_id
            provenance.native_session_id = original.native_session_id
        approved = manual or provenance.reference_mode != "native"
        self.storage.save_image("masks", mask_id, mask)
        self.storage.save_image("masks", mask_id, overlay, ".overlay.png")
        metadata = Mask(
            id=mask_id, scene_id=job.scene.id, width=mask.width, height=mask.height,
            mask_source=source, artifact=ModelArtifact(kind="mask", provenance=provenance),
            edited_from_mask_id=edited_from_mask_id,
            approved=approved, approved_at=utc_now() if approved else None,
            image_url=f"/api/masks/{mask_id}/image", overlay_url=f"/api/masks/{mask_id}/overlay",
            selected_pixels=selected,
            regions=components.regions, min_component_area=threshold,
            discarded_component_count=components.discarded_component_count,
            discarded_pixels=components.discarded_pixels,
            view_id=view_id,
        )
        # Keep AI provenance available after later edits replace the current job snapshot.
        self.storage._write_json(self.storage.artifact_path("masks", mask_id, ".json"), metadata.model_dump_json(indent=2))
        return metadata

    def approve_mask(self, job_id: UUID, mask_id: UUID, view_id: str | None = None) -> WeldJob:
        """Explicit human confirmation of the current, unchanged Canvas mask. No Agent tool."""
        with self.storage.lock:
            job = self.storage.get_job(job_id)
            view_id=view_id or job.scene.primary_view
            if view_id and view_id not in job.scene.views:raise WorkflowError('Unknown scene view.',409)
            metadata=job.scene.views[view_id].mask if view_id else job.mask
            if metadata is None or metadata.id != mask_id:
                raise WorkflowError("The mask changed. Review the current Canvas before approval.", 409)
            if not metadata.approved:
                metadata.approved = True
                metadata.approved_at = utc_now()
                if not view_id or view_id==job.scene.primary_view:job.mask=metadata
                if job.rough3d or job.vla_prediction:StateMachine.replace_mask(job)
                StateMachine.record(job,job.state,"human_mask_confirmation")
                self.storage._write_json(self.storage.artifact_path("masks", mask_id, ".json"), metadata.model_dump_json(indent=2))
                self._save(job)
            return job

    def parse_instruction(self, job_id: UUID, text: str, selection: RegionSelection | None = None) -> WeldJob:
        with self.storage.lock:
            job = self.storage.get_job(job_id)
            StateMachine.require(job, *StateMachine.sequence[2:],WorkflowState.VLA_READY)
            if job.mask is None or not job.mask.approved:
                raise WorkflowError("A confirmed mask is required.", 409)
            return self.apply_instruction(job_id, text, self.parser.parse(text), selection,
                                          parser="dummy-rule-parser")

    def apply_instruction(self, job_id: UUID, text: str, structured: StructuredInstruction,
                          selection: RegionSelection | None = None, *, parser: str = "GPT-Agent") -> WeldJob:
        """Shared validation/transition for manual parsing and semantic agent tools."""
        with self.storage.lock:
            job = self.storage.get_job(job_id)
            StateMachine.require(job, *StateMachine.sequence[2:],WorkflowState.VLA_READY)
            if job.mask is None or not job.mask.approved:
                raise WorkflowError("A confirmed mask is required.", 409)
            structured = resolve_regions(structured, job.mask.regions, selection)
            job.instruction = Instruction(text=text.strip(), structured=structured, parser=parser)
            StateMachine.replace_instruction(job)
            self._save(job)
            return job

    def generate_rough(self, job_id: UUID) -> WeldJob:
        with self.storage.lock:
            job = self.get_job(job_id)
            if job.trajectory_clarification:
                raise WorkflowError('Assistant에서 현재 clarification 질문에 먼저 답해주세요.', 409)
            StateMachine.require(job, WorkflowState.INSTRUCTION_READY)
            image, mask, components = self._conditioning(job)
            if job.instruction is None:
                raise WorkflowError("A parsed instruction is required.", 409)
            started = time.monotonic()
            if job.rough_mode=='native_3d':
                return self._generate_rough3d(job,image,mask,components)
            if getattr(self.rough, 'runtime', None) and job.instruction.structured.direction in ('top_to_bottom','bottom_to_top'):
                raise WorkflowError('세로 방향은 NativeRough3D에서 지원합니다. Native Rough2D baseline은 가로 방향만 지원합니다.',409)
            rough = self.rough.predict(image, mask, job.instruction.structured, components, language=job.instruction.text)
            # Reject malformed adapter output before passing it to a refinement service.
            report = self.validator.validate(
                rough, job.scene, components=components,
                expected_segments=list(enumerate(job.instruction.structured.region_order)),
            )
            if not report.valid:
                runtime = getattr(self.rough, "runtime", None)
                if runtime:
                    runtime.last_error = "MODEL_OUTPUT_INVALID"
                    raise ModelFault("MODEL_OUTPUT_INVALID")
                raise WorkflowError("Rough preview rejected: " + "; ".join(report.errors))
            if rough.artifact is None:
                rough.artifact = ModelArtifact(kind="rough", provenance=Provenance(
                    model_name=rough.generator, model_version="preview-v2", latency_ms=(time.monotonic() - started) * 1000,
                    reference_mode="dummy"))
            rough.artifact.provenance.source_scene_id = job.scene.id
            rough.artifact.provenance.source_mask_id = job.mask.id
            rough.artifact.provenance.instruction = job.instruction.text
            rough.artifact.provenance.region_ids = job.instruction.structured.region_order
            job.rough_trajectory = rough
            StateMachine.advance(job, WorkflowState.ROUGH_PATH_READY)
            self._save(job)
            return job

    def refine(self, job_id: UUID) -> WeldJob:
        if getattr(self.rough, "stops_at_rough", False):
            raise ModelFault("NATIVE_REFINEMENT_DISABLED")
        with self.storage.lock:
            job = self.storage.get_job(job_id)
            StateMachine.require(job, WorkflowState.ROUGH_PATH_READY)
            if job.rough_mode=='native_3d':raise WorkflowError('NativeRough3D는 Guided VLA action을 사용하세요.',409)
            image, mask, _components = self._conditioning(job)
            if job.instruction is None or job.rough_trajectory is None:
                raise WorkflowError("Rough trajectory and instruction are required.", 409)
            started = time.monotonic()
            final = self.vla.refine(image, mask, job.rough_trajectory, job.instruction.text, job.instruction.structured)
            final.artifact = ModelArtifact(kind="final", provenance=Provenance(
                model_name=final.generator, model_version="preview-v2", reference_mode="dummy",
                latency_ms=(time.monotonic() - started) * 1000, source_scene_id=job.scene.id,
                source_mask_id=job.mask.id,
                source_rough_id=job.rough_trajectory.artifact.provenance.artifact_id if job.rough_trajectory.artifact else None,
                instruction=job.instruction.text, region_ids=[s.region_id for s in final.segments]))
            # Point schema already rejects NaN/Inf. Geometry acceptance is the next explicit step.
            job.final_trajectory = final
            StateMachine.advance(job, WorkflowState.VLA_REFINED)
            self._save(job)
            return job

    def validate(self, job_id: UUID) -> WeldJob:
        with self.storage.lock:
            job = self.storage.get_job(job_id)
            StateMachine.require(job, WorkflowState.VLA_REFINED)
            if job.scene is None or job.final_trajectory is None or job.rough_trajectory is None:
                raise WorkflowError("Final preview, rough preview, and scene are required.", 409)
            _image, _mask, components = self._conditioning(job)
            job.validation = self.validator.validate(
                job.final_trajectory, job.scene, components=components,
                expected_segments=[(segment.segment_id, segment.region_id) for segment in job.rough_trajectory.segments],
            )
            job.validation.artifact = ModelArtifact(kind="validation", provenance=Provenance(
                model_name="preview-geometry-validator", model_version="component-v2", reference_mode="dummy", latency_ms=0,
                source_scene_id=job.scene.id, source_mask_id=job.mask.id,
                source_rough_id=job.rough_trajectory.artifact.provenance.artifact_id if job.rough_trajectory.artifact else None,
                instruction=job.instruction.text, region_ids=[s.region_id for s in job.final_trajectory.segments]))
            if job.validation.valid:
                StateMachine.advance(job, WorkflowState.VALIDATED)
            self._save(job)
            if not job.validation.valid:
                raise WorkflowError("Final preview rejected: " + "; ".join(job.validation.errors))
            return job

    def plan(self, job_id: UUID, *, progress=None) -> WeldJob:
        # RLock prevents edits interleaving with a plan in this single-process MVP.
        with self.storage.lock:
            job = self.get_job(job_id)
            StateMachine.require(job, *StateMachine.sequence[3:])
            if job.state == WorkflowState.INSTRUCTION_READY:
                if progress: progress("rough", False, job)
                job = self.generate_rough(job_id)
                if progress: progress("rough", True, job)
            if job.rough_mode=='native_3d' or getattr(self.rough, "stops_at_rough", False):
                return job
            if job.state == WorkflowState.ROUGH_PATH_READY:
                if progress: progress("refine", False, job)
                job = self.refine(job_id)
                if progress: progress("refine", True, job)
            if job.state == WorkflowState.VLA_REFINED:
                if progress: progress("validate", False, job)
                job = self.validate(job_id)
                if progress: progress("validate", True, job)
            return job

    def model_status(self):
        from backend.model_clients.factory import client_status
        return {"segment": client_status(self.segmentation, DummySegmentationClient),
                "rough": client_status(self.rough, DummyRoughPathClient),
                "vla": self.guided_vla.status() if self.guided_vla else client_status(self.vla,DummyVLAClient),
                "rough3d": client_status(self.rough3d,DummyRoughPathClient) if self.rough3d else
                    {'backend':'native','configured':False,'ready':False,'state':'NOT_CONFIGURED','code':None,'reference_mode':'native'}}

    def admit_job(self,job_id):
        """Agent run admission remains strict; the public read is display-tolerant."""
        with self.storage.lock:
            job=self.storage.get_job(job_id)
            if job.trajectory_clarification:
                from backend.orchestrator.clarification import verify_question
                verify_question(self,job)
            if job.native_output and (job.native_output.candidate or job.native_output.preview_urls):
                self.verify_native_output(job)
            return self.get_job(job_id)

    def get_display_job(self,job_id):
        """Public inspection also survives an invalid pending-question lineage."""
        from backend.orchestrator.clarification import ClarificationError
        from backend.model_clients.native_candidate import issue
        with self.storage.lock:
            try:return self.get_job(job_id)
            except ClarificationError:
                job=self.storage.get_job(job_id)
                # A changed question is not trusted display text or reply authority.
                job.trajectory_clarification=None;job.planning_status='NOT_READY'
                if job.native_output:
                    job.native_output.status='NATIVE_OUTPUT_READY_UNVALIDATED'
                    job.native_output.validation=NativeCandidateValidation(status='FAIL',issues=[issue('source_integrity')])
                    job.native_output.candidate=None;job.native_output.preview_urls={}
                job.rough_trajectory=None;job.rough3d=None;job.vla_prediction=None
                self._read_display(job,job.native_output,'trajectory')
                self._read_display(job,job.raw_segment_output,'segment')
                return job

    def get_job(self, job_id: UUID) -> WeldJob:
        with self.storage.lock:
            job=self.storage.get_job(job_id)
            self._restore_segment_display(job)
            if job.trajectory_clarification:
                from backend.orchestrator.clarification import verify_question
                verify_question(self, job)
                self._read_display(job,job.native_output,'trajectory')
                self._read_display(job,job.raw_segment_output,'segment')
                return job
            if job.native_output and (job.native_output.candidate or job.native_output.preview_urls):
                try:self.verify_native_output(job)
                except ModelFault:
                    # Read display evidence, but never accept changed source or approval.
                    from backend.model_clients.native_candidate import issue
                    job.native_output.status='NATIVE_OUTPUT_READY_UNVALIDATED'
                    job.native_output.validation=NativeCandidateValidation(status='FAIL',issues=[issue('source_integrity')])
                    job.native_output.candidate=None;job.native_output.preview_urls={}
                    job.rough_trajectory=None;job.rough3d=None;job.vla_prediction=None
            self._read_display(job,job.native_output,'trajectory')
            self._read_display(job,job.raw_segment_output,'segment')
            # Restore older, proven partial sessions without touching the native
            # files or their immutable output proof and without launching a model.
            if (job.rough_mode == 'native_3d' and job.state == WorkflowState.INSTRUCTION_READY
                    and job.native_output and job.native_output.status == 'PARTIAL_NATIVE_OUTPUT'
                    and job.native_output.native_artifact_id and not job.trajectory_clarification
                    and not any(i.classification == 'HARD_INVALID' for i in job.native_output.validation.issues)):
                from backend.orchestrator.clarification import record_question
                directory, proof = self.verify_native_output(job)
                if record_question(self, job, directory, proof):
                    StateMachine.record(job, job.state, 'native_clarification_pending')
                    self._save(job)
            if job.trajectory_clarification:
                from backend.orchestrator.clarification import verify_question
                verify_question(self, job)
            return job

    def edit_mask(self,job_id,*,operation,relation,view='F'):
        from backend.services.semantic_mask import edit_components
        import io
        with self.storage.lock:
            job=self.get_job(job_id)
            if operation not in ('REMOVE','KEEP_ONLY') or relation not in ('LEFT','RIGHT','TOP','BOTTOM','MIDDLE','FIRST','SECOND'):
                raise WorkflowError('Unsupported mask edit.',422)
            if job.scene is None or (job.scene.views and view not in job.scene.views):
                raise WorkflowError('현재 Scene view를 확인하세요.',409)
            previous=job.scene.views[view].mask if job.scene.views else job.mask
            if previous is None:raise WorkflowError('현재 수정할 마스크가 없습니다.',409)
            mask=self.storage.read_image('masks',previous.id)
            edited,_=edit_components(mask,previous.min_component_area,operation,relation)
            out=io.BytesIO();edited.save(out,format='PNG')
            return self.set_mask(job_id,out.getvalue(),edited_from_mask_id=previous.id,
                                 view_id=view if job.scene.views else None,require_review=True,
                                 min_component_area=previous.min_component_area)

    def refine_mask(self,job_id,*,instruction,view='F'):
        with self.storage.lock:
            job=self.get_job(job_id)
            if view!='F' or job.scene is None or (job.scene.views and view not in job.scene.views):
                raise WorkflowError('현재 Scene view를 확인하세요.',409)
            previous=job.scene.views[view].mask if job.scene.views else job.mask
            if previous is None:raise WorkflowError('먼저 보정할 마스크를 준비해주세요.',409)
            if not hasattr(self.segmentation,'refine'):
                raise ModelFault('MASK_REFINEMENT_MODEL_SUPPORT_PARTIAL')
            image=self._scene_image(job,view if job.scene.views else None)
            current=self.storage.read_image('masks',previous.id)
            # Reject resurrection of stored user removals, without correcting
            # the model's output pixels or silently falling back to detection.
            import numpy as np
            removed=np.zeros((current.height,current.width),dtype=bool)
            child=previous;visited=set()
            while child.edited_from_mask_id is not None:
                parent_id=child.edited_from_mask_id
                if parent_id in visited:raise ModelFault('MODEL_OUTPUT_INVALID')
                visited.add(parent_id)
                parent=Mask.model_validate_json(self.storage.artifact_path('masks',parent_id,'.json').read_text(encoding='utf-8'))
                if parent.scene_id!=previous.scene_id or parent.view_id!=previous.view_id or (parent.width,parent.height)!=current.size:
                    raise ModelFault('NATIVE_INPUT_MISMATCH')
                parent_pixels=np.asarray(self.storage.read_image('masks',parent_id))
                child_pixels=np.asarray(self.storage.read_image('masks',child.id))
                if parent_pixels.shape!=removed.shape or child_pixels.shape!=removed.shape:
                    raise ModelFault('NATIVE_INPUT_MISMATCH')
                if child.mask_source=='manual_edited':
                    removed|=(parent_pixels==255)&(child_pixels==0)
                child=parent
            removed&=np.asarray(current)==0  # A later explicit Brush addition is current human intent.
            image.info['refinement_context']=dict(job_id=job.id,scene_id=job.scene.id,mask_id=previous.id)
            current.info['removed_pixels']=removed  # Local validation only; never external conditioning.
            try:
                refined=self.segmentation.refine(image,current,previous,instruction=instruction)
                validate_binary_mask(refined,current.size)
                if np.any(removed&(np.asarray(refined)==255)):
                    raise ModelFault('MASK_REFINEMENT_CONSTRAINT_VIOLATION')
                if not detect_components(refined,previous.min_component_area).regions:
                    raise ModelFault('MASK_REFINEMENT_EMPTY_MASK')
            except (ModelFault,WorkflowError):
                if getattr(self.segmentation,'last_result',None) is not None:
                    self._segment_output(job,False);self._save(job)
                raise
            self._segment_output(job,True)
            metadata=self._store_mask(job,image,refined,previous,view,previous.min_component_area,None,False)
            metadata.mask_source='ai_refined';metadata.approved=False;metadata.approved_at=None
            metadata.edited_from_mask_id=previous.id
            self.storage._write_json(self.storage.artifact_path('masks',metadata.id,'.json'),metadata.model_dump_json(indent=2))
            if job.scene.views:job.scene.views[view].mask=metadata
            if not job.scene.views or view==job.scene.primary_view:job.mask=metadata
            StateMachine.replace_mask(job);self._save(job)
            return job

    def answer_trajectory_clarification(self, job_id, clarification_id, answer):
        """Claim one reply; consume only a validated result or a new native question."""
        from backend.orchestrator.clarification import (answer_direction, resolved_instruction, verify_question,
            resolution_supported, ClarificationError, write_once, failed_reply_reason)
        with self.storage.lock:
            job = self.get_job(job_id)
            pending = job.trajectory_clarification
            if not pending or pending.id != clarification_id:
                raise ClarificationError('CLARIFICATION_STALE')
            StateMachine.require(job, WorkflowState.INSTRUCTION_READY)
            if job.rough_mode != 'native_3d' or self.rough3d is None:
                raise ClarificationError('TRAJECTORY3_ADMISSION_FAILED', 503)
            record = verify_question(self, job)
            direction = answer_direction(answer)
            if not direction:
                return job  # Ambiguous/unsupported answers cannot authorize a model.
            if not resolution_supported(pending, direction):
                raise ClarificationError('CLARIFICATION_ANSWER_UNSUPPORTED', 422)
            context = self.storage.root / 'native_context'
            for claim in context.glob(f'{pending.id}.*.clarification-claim.json'):
                outcome = claim.with_name(claim.name.replace('.clarification-claim.json','.clarification-outcome.json'))
                try:
                    finished = json.loads(outcome.read_text(encoding='utf-8'))
                    claimed = json.loads(claim.read_text(encoding='utf-8'))
                    retryable = (finished['claim_id'] == claimed['claim_id'] and
                                 finished['status'] == 'failed' and finished['retryable'] is True)
                except (OSError, ValueError, KeyError, TypeError):
                    retryable = False
                if not retryable:
                    raise ClarificationError('CLARIFICATION_RECOVERY_REQUIRED')
            resolved = resolved_instruction(direction)
            structured = job.instruction.structured.model_copy(update={'direction': direction})
            # Immutable receipts retain the original instruction and the exact
            # explicit answer; only the consistent resolved text goes to native.
            claim_id = uuid4()
            receipt = dict(job_id=str(job.id), clarification_id=str(pending.id), claim_id=str(claim_id),
                original_instruction=record['original_instruction'], clarification_answer=answer,
                resolved_instruction=resolved, answered_at=utc_now().isoformat(),
                source_native_artifact_id=record['native_artifact_id'], mask_id=str(job.mask.id),
                approved_mask_hash=record['approved_mask_hash'], approval_timestamp=record['approval_timestamp'])
            claim = context / f'{pending.id}.{claim_id}.clarification-claim.json'
            outcome = claim.with_name(claim.name.replace('.clarification-claim.json','.clarification-outcome.json'))
            try:
                write_once(claim, dict(receipt, status='claimed'))
            except OSError:
                raise ClarificationError('CLARIFICATION_RECOVERY_REQUIRED') from None
            # Keep the persisted original pending question until native settles.
            # The draft carries resolved language and exact region/approval data.
            draft = job.model_copy(deep=True)
            draft.clarification_history.append(pending.id)
            draft.instruction = Instruction(text=resolved, structured=structured, parser='human-clarification')
            StateMachine.replace_instruction(draft)
            runtime = getattr(self.rough3d, 'runtime', None)
            if runtime is not None and hasattr(runtime,'last_capture'):
                runtime.last_capture = None
            try:
                image, mask, components = self._conditioning(draft)
                result = self._generate_rough3d(draft, image, mask, components, preserve_failure_code=True)
                capture = getattr(runtime, 'last_capture', None)
                if capture and capture.get('exit_code') != 0:
                    raise ClarificationError('TRAJECTORY3_TIMEOUT' if getattr(runtime,'last_error',None)=='MODEL_TIMEOUT' else 'TRAJECTORY3_NATIVE_FAILED', 503)
                if not result.trajectory_clarification and not (result.state == WorkflowState.ROUGH_PATH_READY and result.rough3d):
                    raise ClarificationError('TRAJECTORY3_OUTPUT_INVALID', 422)
            except Exception as exc:
                fault = failed_reply_reason(exc, runtime)
                try:
                    # Retain failed native evidence independently; restore the
                    # original question/instruction, never the original outputs.
                    write_once(context/f'{pending.id}.{claim_id}.clarification-failed-job.json', draft.model_dump(mode='json'))
                    self._save(job)
                    capture = getattr(runtime,'last_capture',None) or {}
                    write_once(outcome, dict(claim_id=str(claim_id), status='failed', reason_code=fault.code,
                        completed_at=utc_now().isoformat(), retryable=True,
                        native_artifact_id=capture.get('artifact_id'), native_exit_code=capture.get('exit_code')))
                except OSError:
                    raise ClarificationError('CLARIFICATION_RECOVERY_REQUIRED') from None
                raise fault from None
            try:
                write_once(outcome, dict(claim_id=str(claim_id), status='consumed',
                    completed_at=utc_now().isoformat(), retryable=False,
                    result='repeated_clarification' if result.trajectory_clarification else 'success',
                    next_clarification_id=str(result.trajectory_clarification.id) if result.trajectory_clarification else None))
                write_once(self.storage.artifact_path('native_context', pending.id, '.clarification-answer.json'),
                    dict(receipt, status='consumed'))
            except OSError:
                raise ClarificationError('CLARIFICATION_RECOVERY_REQUIRED') from None
            return result

    def _conditioning(self, job: WeldJob):
        if job.scene is None or job.mask is None:
            raise WorkflowError("Scene and confirmed mask are required.", 409)
        image = self._scene_image(job)
        mask = self.storage.read_image("masks", job.mask.id)
        if not job.mask.approved:
            raise ModelFault("NATIVE_MASK_NOT_APPROVED")
        # Backend-owned context travels with the binary conditioning image, like Segment provenance.
        mask.info["mask_artifact"] = job.mask
        return image, mask, detect_components(mask, job.mask.min_component_area)

    def _save(self, job: WeldJob) -> None:
        if job.scene and job.scene.primary_view:
            job.scene.views[job.scene.primary_view].mask=job.mask
        self.storage.save_trajectories(job)
        self.storage.save_job(job)

    def select_rough_mode(self,job_id,mode):
        with self.storage.lock:
            job=self.get_job(job_id)
            if mode=='native_3d' and not (job.scene and job.scene.views):raise WorkflowError('NativeRough3D에는 dataset Scene이 필요합니다.',409)
            if job.rough_mode!=mode:
                job.rough_mode=mode;StateMachine.clear_trajectories(job)
                StateMachine.record(job,WorkflowState.INSTRUCTION_READY if job.instruction else WorkflowState.MASK_READY if job.mask else WorkflowState.SCENE_READY,'rough_mode_changed')
                self._save(job)
            return job

    def _generate_rough3d(self,job,image,mask,components,*,preserve_failure_code=False):
        if self.rough3d is None:raise ModelFault('MODEL_NOT_CONFIGURED')
        from backend.model_clients.guidance_preview import guidance_preview
        from backend.model_clients.native_approval import pixel_hash
        from backend.model_clients.native import sha256,read_json,NativeRuntime
        from backend.model_clients.native_candidate import read_candidate,validate_candidate,issue,CandidateInvalid
        runtime=getattr(self.rough3d,'runtime',None)
        if runtime is not None and hasattr(runtime,'last_capture'):
            runtime.last_capture=None # Never recover a previous attempt after preflight fails.
            runtime.last_display_capture=None
        try:
            result=self.rough3d.predict(image,mask,job.instruction.structured,components,language=job.instruction.text)
        except ModelFault as fault:
            capture=getattr(getattr(self.rough3d,'runtime',None),'last_capture',None)
            try:self._preserve_partial_native(job,mask,capture,fault_code=fault.code)
            finally:self._recover_display(job,getattr(runtime,'last_display_capture',None))
            if job.native_output.candidate or job.trajectory_clarification:
                return job
            if preserve_failure_code:
                raise
            raise ModelFault('NATIVE_OUTPUT_MISSING' if not job.native_output.validation.issues or
                             all(i.classification=='SOFT_WARNING' for i in job.native_output.validation.issues)
                             else 'NATIVE_OUTPUT_HARD_INVALID') from None
        if not result.artifact:
            self._recover_display(job,getattr(runtime,'last_display_capture',None))
            raise ModelFault('MODEL_OUTPUT_INVALID')
        files={p.relative_to(result.directory).as_posix():sha256(p) for p in result.directory.rglob('*') if p.is_file()}
        meta=result.artifact.provenance
        capture=getattr(getattr(self.rough3d,'runtime',None),'last_capture',None)
        if isinstance(runtime,NativeRuntime) and capture is None:
            self._recover_display(job,getattr(runtime,'last_display_capture',None))
            raise ModelFault('NATIVE_OUTPUT_HARD_INVALID') # Never downgrade a failed native evidence capture.
        if capture and (capture['artifact_id']!=str(meta.artifact_id) or capture['files']!=files):
            self._recover_display(job,getattr(runtime,'last_display_capture',None))
            raise ModelFault('NATIVE_OUTPUT_HARD_INVALID')
        known={'F:polyline_0'}
        if capture:
            self.rough3d.approvals.verify(Path(capture['mask_session']),mask,job.mask)
            accepted=read_json(Path(capture['mask_session'])/'iteration_001/result.json')
            known={f'{v}:polyline_{i}' for v,p in accepted['predictions'].items() for i in range(len(p['polylines']))}
        try:
            candidate,data=read_candidate(result.directory,job.scene.sample_id,job.instruction.text,meta.artifact_id,job.scene,known_masks=known)
        except CandidateInvalid as exc:
            job.native_output=NativeOutputReport(status='NATIVE_OUTPUT_READY_UNVALIDATED',native_output_generated=True,
                native_artifact_id=meta.artifact_id,source_session=result.directory.name,
                validation=NativeCandidateValidation(status='FAIL',issues=[exc.issue]))
            self._seal_native_output(job,result.directory,files)
            StateMachine.record(job,job.state,'native_output_hard_invalid');self._save(job)
            raise ModelFault('NATIVE_OUTPUT_HARD_INVALID') from None
        preview=None;report=None
        try:
            preview=guidance_preview(result,components,job.instruction.structured)
            report=self.validator.validate(preview,job.scene,components=components,
                expected_segments=list(enumerate(job.instruction.structured.region_order)))
        except ModelFault:
            pass  # Strict Guided acceptance is independent from safe native geometry display.
        validation=validate_candidate(candidate,data,components,job.instruction.structured,report)
        if preview is None and not validation.issues:
            validation=NativeCandidateValidation(status='FAIL',issues=[issue('guided_contract','SOFT_WARNING')])
        hard=any(i.classification=='HARD_INVALID' for i in validation.issues)
        job.native_output=NativeOutputReport(
            status='NATIVE_OUTPUT_VALIDATED' if validation.status=='PASS' else 'NATIVE_OUTPUT_READY_UNVALIDATED',
            native_output_generated=True,native_artifact_id=meta.artifact_id,source_session=result.directory.name,
            candidate=None if hard else candidate,validation=validation,artifacts=meta.native_artifacts)
        job.validation=report if validation.status!='PASS' else None
        self._seal_native_output(job,result.directory,files)
        if validation.status!='PASS':
            StateMachine.record(job,job.state,'native_output_generated_validation_failed');self._save(job)
            if hard:raise ModelFault('NATIVE_OUTPUT_HARD_INVALID')
            return job
        meta.source_scene_id=job.scene.id;meta.source_mask_id=job.mask.id;meta.input_mask_sha256=pixel_hash(mask)
        meta.instruction=job.instruction.text;meta.region_ids=job.instruction.structured.region_order
        job.rough_trajectory=preview
        job.planning_status='READY'
        reference=result.reference_trajectory_3d
        job.rough3d=Rough3DArtifact(artifact_id=meta.artifact_id,native_session_id=result.directory.name,
            reference_preview_url=f'/api/weld/{job.id}/rough3d/reference-preview',
            source_mask_id=job.mask.id,source_mask_sha256=pixel_hash(mask),approved_at=job.mask.approved_at,
            image_guidance_point_count=result.image_guidance_2d['actual_point_count'],
            reference_sample_id=reference.source_sample_id,reference_coordinate_frame=reference.coordinate_frame,
            reference_point_count=reference.actual_point_count,artifacts=meta.native_artifacts)
        self.storage._write_json(self.storage.artifact_path('native_context',meta.artifact_id,'.rough3d.json'),json.dumps(
            {'directory':str(result.directory),'job_id':str(job.id),'mask_id':str(job.mask.id),
             'files':{name:sha256(result.directory/name)
                      for name in ('query_image_guidance_2d.json','reference_trajectory_3d.json','iteration_001/plan.json',
                                   'iteration_001/cot_ko.md','iteration_001/vla_prompt.md','iteration_001/rough_trajectory_3d.jpg')}},ensure_ascii=False))
        StateMachine.advance(job,WorkflowState.ROUGH_PATH_READY);self._save(job);return job

    def _seal_native_output(self,job,directory,files):
        """Immutable candidate/proof owned by this job; filesystem paths stay private."""
        import hashlib
        from backend.model_clients.native import sha256
        from backend.model_clients.native_approval import pixel_hash
        output=job.native_output
        from backend.model_clients.model_display import seal
        seal(self.storage,job,output,directory,'trajectory')
        for kind,name in self._native_images().items():
            if name in files and not any(i.classification=='HARD_INVALID' for i in output.validation.issues):
                output.preview_urls[kind]=f'/api/weld/{job.id}/native-output/image/{kind}'
        if any(sha256(directory/name)!=value for name,value in files.items()):
            raise ModelFault('NATIVE_OUTPUT_HARD_INVALID')
        proof=dict(directory=str(directory),files=files,job_id=str(job.id),sample_id=job.scene.sample_id,
            mask_id=str(job.mask.id),mask_sha256=sha256(self.storage.artifact_path('masks',job.mask.id)),
            mask_pixels_sha256=pixel_hash(self.storage.read_image('masks',job.mask.id)),
            approved_at=job.mask.approved_at.isoformat(),
            instruction_sha256=hashlib.sha256(job.instruction.model_dump_json().encode()).hexdigest(),
            output_sha256=hashlib.sha256(output.model_dump_json().encode()).hexdigest())
        capture=getattr(getattr(self.rough3d,'runtime',None),'last_capture',None)
        if capture and capture['artifact_id']==str(output.native_artifact_id):
            session=Path(capture['mask_session'])
            approved=self.rough3d.approvals.verify(session,self.storage.read_image('masks',job.mask.id),job.mask)
            approved_proof=session.parent/f'{session.name}.json'
            proof['approved_session']=dict(directory=str(session),files=approved['files'],
                proof_sha256=sha256(approved_proof))
        path=self.storage.artifact_path('native_context',output.native_artifact_id,'.native-output.json')
        with path.open('x',encoding='utf-8') as stream:json.dump(proof,stream,ensure_ascii=False)

    def _recover_display(self,job,capture):
        from backend.model_clients.model_display import seal
        from backend.model_clients.native_candidate import issue
        if not capture or capture['sample_id']!=job.scene.sample_id:return
        output=job.native_output
        if output and output.model_output and str(output.native_artifact_id)==capture['artifact_id']:
            self._save(job);return
        if output is None or output.native_artifact_id is None or str(output.native_artifact_id)!=capture['artifact_id']:
            output=NativeOutputReport(status='NATIVE_OUTPUT_READY_UNVALIDATED',native_output_generated=True,
                native_artifact_id=capture['artifact_id'],validation=NativeCandidateValidation(status='FAIL',issues=[issue('source_integrity')]))
            job.native_output=output
        seal(self.storage,job,output,Path(capture['directory']),'trajectory')
        if output.model_output.point_count:output.native_output_generated=True
        self._save(job)

    def _restore_segment_display(self,job):
        """Older successful masks already carry a bound native artifact UUID."""
        if job.raw_segment_output or not job.mask or not job.mask.artifact or not job.scene.views:return
        from backend.model_clients.native import read_json,sha256
        from backend.model_clients.config import ROOT
        from backend.model_clients.model_display import seal
        from backend.model_clients.native_candidate import issue
        source_id=job.mask.artifact.provenance.native_source_artifact_id
        records=getattr(getattr(self.segmentation,'runtime',None),'records',None)
        if not source_id or records is None:return
        try:
            record=read_json(Path(records)/f'{source_id}.json');directory=Path(record['directory']).resolve()
            if (record['sample_id']!=job.scene.sample_id or not directory.is_relative_to(ROOT.resolve())
                    or job.mask.artifact.provenance.source_scene_id!=job.scene.id):return
            names=('iteration_001/result.json','iteration_001/F_prediction.png')
            valid=all(record['files'].get(name)==sha256(directory/name) for name in names)
            output=NativeOutputReport(status='NATIVE_OUTPUT_VALIDATED' if valid else 'NATIVE_OUTPUT_READY_UNVALIDATED',
                native_output_generated=True,native_artifact_id=source_id,
                validation=NativeCandidateValidation(status='PASS' if valid else 'FAIL',issues=[] if valid else [issue('source_integrity')]))
            seal(self.storage,job,output,directory,'segment')
            job.raw_segment_output=output
        except (OSError,ValueError,KeyError,TypeError):return

    def _read_display(self,job,output,stage):
        if output is None:return
        from backend.model_clients.model_display import verified,seal
        from backend.schemas import ModelOutputDisplay
        if output.model_output is None and output.native_artifact_id and stage=='trajectory':
            # Bounded read of this job's previous owned proof; no native rerun.
            from backend.model_clients.native import read_json
            from backend.model_clients.config import ROOT
            try:
                proof=read_json(self.storage.artifact_path('native_context',output.native_artifact_id,'.native-output.json'))
                directory=Path(proof['directory']).resolve()
                allowed=(ROOT/'.cache',ROOT.parent/'vlm_trajectory2/outputs',ROOT.parent/'vlm_trajectory3/outputs')
                if (proof['job_id']==str(job.id) and proof['sample_id']==job.scene.sample_id
                        and any(directory.is_relative_to(p.resolve()) for p in allowed)):
                    seal(self.storage,job,output,directory,stage)
            except (OSError,ValueError,KeyError,TypeError):pass
        if output.model_output is None:return
        try:
            display,_=verified(self.storage,job,output,stage)
            if output.validation.status!='PASS':
                display.guided_vla_allowed=False
                if display.displayable:display.status='OUTPUT_RAW_DISPLAYABLE'
            output.model_output=display
        except (OSError,ValueError,KeyError,TypeError):
            output.model_output=ModelOutputDisplay(available=True,status='OUTPUT_MALFORMED',warnings=['DISPLAY_EVIDENCE_INVALID'])
            from backend.model_clients.native_candidate import issue
            output.status='NATIVE_OUTPUT_READY_UNVALIDATED'
            output.validation=NativeCandidateValidation(status='FAIL',issues=[issue('source_integrity')])
            if stage=='trajectory':
                output.candidate=None;output.preview_urls={}
                job.rough_trajectory=None;job.rough3d=None;job.vla_prediction=None

    def segment_output_image(self,job_id,view):
        from backend.model_clients.model_display import verified
        with self.storage.lock:
            job=self.get_job(job_id)
            try:
                display,folder=verified(self.storage,job,job.raw_segment_output,'segment')
                if view not in display.mask_urls:raise ValueError()
                return folder/f'{view}.png'
            except (AttributeError,OSError,ValueError,KeyError,TypeError):
                raise WorkflowError('표시할 모델 마스크가 없습니다.',404) from None

    def _preserve_partial_native(self,job,mask,capture,*,fault_code=None):
        import hashlib
        from backend.model_clients.native import read_json,read_native_result,sha256
        from backend.model_clients.native_candidate import issue,read_candidate,validate_candidate,CandidateInvalid
        from backend.model_clients.native_rough3d import NativeRough3DResult
        from backend.model_clients.trajectory_contracts import ReferenceTrajectory3D
        from backend.model_clients.guidance_preview import guidance_preview
        artifacts={};directory=None;hard=fault_code in ('NATIVE_INPUT_MISMATCH','NATIVE_MASK_NOT_APPROVED','MODEL_OUTPUT_INVALID')
        if capture:
            try:
                if (not capture.get('trusted_input_snapshot') or capture['sample_id']!=job.scene.sample_id
                        or capture['instruction_sha256']!=hashlib.sha256(job.instruction.text.encode()).hexdigest()):raise ValueError()
                self.rough3d.approvals.verify(Path(capture['mask_session']),mask,job.mask)
                directory=Path(capture['directory']);artifacts={name:True for name in capture['files']}
                if any(sha256(directory/name)!=h for name,h in capture['files'].items()):raise ValueError()
            except (ModelFault,OSError,ValueError,KeyError):hard=True
        if directory and not hard and 'iteration_001/plan.json' in artifacts:
            # A missing visualization/report must not hide safely parsed original
            # points. All identity, native copies, references and approval gates
            # still run; this recovered candidate is NEVER accepted downstream.
            candidate=None;validation=None
            try:
                data=read_native_result('rough3d',directory,job.scene.sample_id,job.instruction.text,
                    version=capture['native_stack'],strict_aux=False)
                if capture['native_stack']=='native_3d_v3' and Path(data['previous_mask_session']).resolve()!=Path(capture['mask_session']).resolve():
                    raise CandidateInvalid('native_metadata')
                accepted=read_json(Path(capture['mask_session'])/'iteration_001/result.json')
                known={f'{v}:polyline_{i}' for v,p in accepted['predictions'].items() for i in range(len(p['polylines']))}
                candidate,data=read_candidate(directory,job.scene.sample_id,job.instruction.text,capture['artifact_id'],job.scene,known_masks=known)
                components=detect_components(mask,job.mask.min_component_area)
                result=NativeRough3DResult(job.scene.sample_id,directory,data['image_guidance_2d'],
                    ReferenceTrajectory3D.model_validate(data['rough_trajectory_3d']),data['plan'])
                report=None
                try:
                    preview=guidance_preview(result,components,job.instruction.structured)
                    report=self.validator.validate(preview,job.scene,components=components,
                        expected_segments=list(enumerate(job.instruction.structured.region_order)))
                except ModelFault:pass
                validation=validate_candidate(candidate,data,components,job.instruction.structured,report)
                validation.status='FAIL';validation.issues.append(issue('auxiliary_artifacts','SOFT_WARNING'))
            except CandidateInvalid as exc:
                validation=NativeCandidateValidation(status='FAIL',issues=[exc.issue])
            except (ModelFault,OSError,ValueError,KeyError,TypeError):
                validation=NativeCandidateValidation(status='FAIL',issues=[issue('native_metadata')])
            if any(i.classification=='HARD_INVALID' for i in validation.issues):candidate=None
            job.native_output=NativeOutputReport(status='NATIVE_OUTPUT_READY_UNVALIDATED',native_output_generated=True,
                native_artifact_id=capture['artifact_id'],source_session=directory.name,candidate=candidate,
                validation=validation,artifacts=artifacts)
            self._seal_native_output(job,directory,capture['files'])
            StateMachine.record(job,job.state,'native_candidate_recovered');self._save(job);return
        from backend.orchestrator.clarification import extract
        clarification='iteration_001/clarification.json' in artifacts or bool(directory and not hard and extract(directory, capture['files']))
        job.native_output=NativeOutputReport(status='PARTIAL_NATIVE_OUTPUT' if artifacts else 'NATIVE_OUTPUT_MISSING',
            native_output_generated=False,native_artifact_id=capture['artifact_id'] if capture else None,
            source_session=directory.name if directory else None,artifacts=artifacts,
            validation=NativeCandidateValidation(status='FAIL' if hard else 'WARN',issues=[
                issue('source_integrity') if hard else issue('native_clarification' if clarification else 'native_incomplete','SOFT_WARNING')]))
        if directory and not hard:
            self._seal_native_output(job,directory,capture['files'])
            from backend.orchestrator.clarification import record_question
            directory,proof=self.verify_native_output(job)
            record_question(self,job,directory,proof)
        StateMachine.record(job,job.state,'native_partial_or_missing_output');self._save(job)

    @staticmethod
    def _native_images():
        return dict(guidance='iteration_001/image_guidance_2d_overlay.jpg',
            reference='iteration_001/rough_trajectory_3d.jpg',review='iteration_001/review_all.jpg',query='query_views.jpg')

    def verify_native_output(self,job):
        from backend.model_clients.native_candidate import verify_snapshot,CandidateInvalid
        try:
            return verify_snapshot(self.storage,job)
        except CandidateInvalid:
            raise ModelFault('NATIVE_OUTPUT_HARD_INVALID') from None

    def native_output_image(self,job_id,kind):
        with self.storage.lock:
            job=self.get_job(job_id)
            if kind not in self._native_images() or not job.native_output or kind not in job.native_output.preview_urls:
                raise WorkflowError('해당 native 시각화가 없습니다.',404)
            directory,_=self.verify_native_output(job)
            return directory/self._native_images()[kind]

    @property
    def final_predictor(self):
        # Compatibility slot for injected Guided VLA fixtures and older clients.
        return self.guided_vla

    def run_guided_vla(self,job_id):
        if self.get_job(job_id).state==WorkflowState.VLA_READY:
            raise WorkflowError('현재 Guided VLA 결과가 이미 있습니다.',409)
        if self.final_predictor and self.final_predictor.status().get('backend')=='gpt':
            from backend.model_clients.guided_vla import GuidedVLAError
            raise GuidedVLAError('FINAL_TRAJECTORY_BACKEND_MISMATCH')
        return self.run_final_trajectory_prediction(job_id)

    def run_final_trajectory_prediction(self,job_id):
        with self.storage.lock:
            job=self.get_job(job_id)
            if job.vla_prediction and job.state==WorkflowState.VLA_READY:
                self.final_predictor.verify_current(self.storage,job)
                return job  # Idempotent explicit action; never generate twice.
            if job.native_output:
                if job.native_output.status!='NATIVE_OUTPUT_VALIDATED' or job.native_output.validation.status!='PASS':
                    raise ModelFault('NATIVE_OUTPUT_VALIDATION_REQUIRED')
                self.verify_native_output(job)
            StateMachine.require(job,WorkflowState.ROUGH_PATH_READY)
            if not job.rough3d or not job.mask or not job.mask.approved or self.guided_vla is None:
                raise WorkflowError('현재 승인 F mask와 NativeRough3D guidance가 필요합니다.',409)
            try:
                summary=self.final_predictor.run(self.storage,job)
            finally:
                display=getattr(self.final_predictor,'last_display',None)
                if display:
                    job.raw_final_prediction=display
                    self._save(job)
            if summary.sample_id!=job.scene.sample_id or summary.split!=job.scene.split or summary.mask_views!=['F']:
                raise ModelFault('MODEL_OUTPUT_INVALID')
            job.vla_prediction=summary
            StateMachine.advance(job,WorkflowState.VLA_READY);self._save(job);return job

    def rough3d_reference_preview(self,job_id):
        """Read only the native teaching-reference visual; no raw point/Markdown route."""
        from backend.model_clients.native import read_json,sha256
        from backend.model_clients.config import ROOT
        with self.storage.lock:
            job=self.get_job(job_id)
            if not job.rough3d:raise WorkflowError('현재 Rough3D reference가 없습니다.',409)
            proof=read_json(self.storage.artifact_path('native_context',job.rough3d.artifact_id,'.rough3d.json'))
            directory=Path(proof['directory']).resolve()
            allowed=(ROOT/'.cache',ROOT.parent/'vlm_trajectory2/outputs')
            name='iteration_001/rough_trajectory_3d.jpg';path=directory/name
            if (not any(directory.is_relative_to(root.resolve()) for root in allowed)
                    or not path.resolve().is_relative_to(directory) or sha256(path)!=proof['files'][name]):
                raise ModelFault('MODEL_OUTPUT_INVALID')
            return path
