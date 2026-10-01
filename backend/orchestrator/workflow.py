from uuid import UUID, uuid4
import time
import json
from pathlib import Path

from backend.model_clients.contracts import ModelArtifact, ModelFault, Provenance
from backend.model_clients.workflow_contracts import Rough3DClient, GuidedWorkflowClient

from backend.orchestrator.instruction_parser import DummyInstructionParser, InstructionParser
from backend.orchestrator.region_selection import resolve_regions
from backend.orchestrator.state_machine import StateMachine, WorkflowError
from backend.schemas import Instruction, Mask, RegionSelection, Scene, SceneView, Rough3DArtifact,VLAResultSummary, StateEvent, StructuredInstruction, WeldJob, WorkflowState, utc_now
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
        self.guided_vla=guided_vla

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
                 view_id: str | None = None) -> WeldJob:
        with self.storage.lock:
            job = self.storage.get_job(job_id)
            StateMachine.require(job, *StateMachine.sequence[1:],WorkflowState.VLA_READY)
            if job.scene is None:
                raise WorkflowError("A scene is required.", 409)
            view_id=view_id or job.scene.primary_view
            if view_id is not None and view_id not in job.scene.views:raise WorkflowError('Unknown scene view.',409)
            if data is None and job.scene.views and hasattr(self.segmentation,'segment_views'):
                masks=self.segmentation.segment_views(self._scene_image(job,'F'),instruction=instruction)
                if 'F' not in masks or any(v not in job.scene.views for v in masks):raise ModelFault('MODEL_OUTPUT_INVALID')
                # Validate the entire output before committing any view.
                for v,m in masks.items():
                    validate_binary_mask(m,(job.scene.views[v].width,job.scene.views[v].height))
                    if not detect_components(m,min_component_area or self.min_component_area).regions:raise ModelFault('MODEL_OUTPUT_INVALID')
                for v,m in masks.items():
                    job.scene.views[v].mask=self._store_mask(job,self._scene_image(job,v),m,
                        job.scene.views[v].mask,v,min_component_area,None,False)
                job.mask=job.scene.views['F'].mask
                StateMachine.replace_mask(job);self._save(job);return job
            previous=job.scene.views[view_id].mask if view_id else job.mask
            image = self._scene_image(job,view_id)
            if edited_from_mask_id is not None and (data is None or previous is None or previous.id != edited_from_mask_id):
                raise WorkflowError("The edited mask base has changed. Reload the current mask.", 409)
            mask = decode_image(data, mask=True) if data is not None else self.segmentation.segment(image, instruction=instruction)
            metadata=self._store_mask(job,image,mask,previous,view_id,min_component_area,edited_from_mask_id,data is not None)
            if view_id:job.scene.views[view_id].mask=metadata
            if not view_id or view_id==job.scene.primary_view:job.mask=metadata
            StateMachine.replace_mask(job)
            self._save(job)
            return job

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
        edited = manual and edited_from_mask_id is not None and previous.mask_source in ("vlm_segment", "manual_edited", "automatic")
        source = "manual_edited" if edited else "manual" if manual else "vlm_segment" if model_provenance else "automatic"
        provenance = model_provenance or Provenance(
            model_name="manual-mask" if manual else "dummy-segmentation",
            model_version="binary-mask-v1", latency_ms=(time.monotonic() - started) * 1000,
            reference_mode="dummy", source_mask_id=edited_from_mask_id)
        provenance.source_scene_id = job.scene.id
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
                job.history.append(StateEvent(state=job.state, reason="human_mask_confirmation"))
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
            job = self.storage.get_job(job_id)
            StateMachine.require(job, WorkflowState.INSTRUCTION_READY)
            image, mask, components = self._conditioning(job)
            if job.instruction is None:
                raise WorkflowError("A parsed instruction is required.", 409)
            started = time.monotonic()
            if job.rough_mode=='native_3d':
                return self._generate_rough3d(job,image,mask,components)
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
            job = self.storage.get_job(job_id)
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

    def get_job(self, job_id: UUID) -> WeldJob:
        with self.storage.lock:
            return self.storage.get_job(job_id)

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

    def _generate_rough3d(self,job,image,mask,components):
        if self.rough3d is None:raise ModelFault('MODEL_NOT_CONFIGURED')
        if len(components.regions)!=1 or job.instruction.structured.region_order!=[components.regions[0].region_id]:
            raise WorkflowError('현재 Guided VLA contract는 독립 F 용접 영역 하나를 지원합니다. 여러 영역은 2D baseline을 사용하세요.',409)
        from backend.model_clients.guidance_preview import guidance_preview
        from backend.model_clients.native_approval import pixel_hash
        from backend.model_clients.native import sha256
        result=self.rough3d.predict(image,mask,job.instruction.structured,components,language=job.instruction.text)
        preview=guidance_preview(result,components,job.instruction.structured)
        report=self.validator.validate(preview,job.scene,components=components,expected_segments=list(enumerate(job.instruction.structured.region_order)))
        if not report.valid or not result.artifact:raise ModelFault('MODEL_OUTPUT_INVALID')
        meta=result.artifact.provenance
        meta.source_scene_id=job.scene.id;meta.source_mask_id=job.mask.id;meta.input_mask_sha256=pixel_hash(mask)
        meta.instruction=job.instruction.text;meta.region_ids=job.instruction.structured.region_order
        job.rough_trajectory=preview
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

    def run_guided_vla(self,job_id):
        with self.storage.lock:
            job=self.get_job(job_id);StateMachine.require(job,WorkflowState.ROUGH_PATH_READY)
            if not job.rough3d or not job.mask or not job.mask.approved or self.guided_vla is None:
                raise WorkflowError('현재 승인 F mask와 NativeRough3D guidance가 필요합니다.',409)
            summary=self.guided_vla.run(self.storage,job)
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
