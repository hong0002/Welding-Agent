"""Current-job adapter for the already validated F-only Guided VLA contract.

CLI discovery is unchanged. The user-triggered workflow uses the existing
GuidedVLAClient.execute and its exact single-F multipart writer. R/S4 remain
review artifacts and are never packaged here. Automated tests inject transport.
"""
from pathlib import Path
from uuid import UUID,uuid4
import json
import time
import httpx
import numpy as np
from backend.model_clients.guided_vla import (GuidedVLAClient,GuidedVLAError,
    HTTPGuidedTransport,resolve_split,serialize_guidance,write_json,write_bytes,digest)
from backend.model_clients.native import NativeBinding,read_json,sha256
from backend.model_clients.native_approval import pixel_hash
from backend.model_clients.native_rough3d import NativeRough3DClient
from backend.services.components import detect_components
from backend.services.mask_service import validate_binary_mask
from backend.schemas import VLAResultSummary


def conditioning_hash(job):
    payload={k:job.model_dump(mode='json')[k] for k in ('scene','mask','instruction','rough_mode','rough3d','rough_trajectory')}
    if job.native_output:payload['native_output']=job.native_output.model_dump(mode='json')
    return digest(json.dumps(payload,sort_keys=True,ensure_ascii=False,allow_nan=False).encode())


class WorkflowGuidedVLAClient(GuidedVLAClient):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self._ready=False;self._checked=0.;self._manifest_hashes={};self.last_code=None;self._model=None

    def status(self):
        configured=bool(self.settings.api_token) or self.transport is not None
        ready=configured and self._ready and time.monotonic()-self._checked<60
        return dict(backend='guided',configured=configured,ready=ready,state='READY' if ready else 'UNVERIFIED' if configured else 'NOT_CONFIGURED',
                    code=self.last_code,reference_mode=None,token_configured=bool(self.settings.api_token),mask_views=['F'])

    def check_server(self):
        if not self.status()['configured']:raise GuidedVLAError('GUIDED_VLA_TOKEN_REQUIRED')
        try:
            if self.transport is not None and not isinstance(self.transport,HTTPGuidedTransport):
                value=self.transport.health()
            else:
                # /health is explicit in the deployed EX3 documentation. No
                # inference, redirects, retries, environment proxies or logging.
                with httpx.Client(trust_env=False,follow_redirects=False,timeout=8) as client:
                    response=client.get(self.settings.server_url.rstrip('/')+'/health',headers={'X-API-Key':self.settings.api_token})
                    response.raise_for_status();value=response.json()
            if value.get('status')!='ready' or value.get('waypoints')!=9 or value.get('dimensions')!=3:raise ValueError('Not ready')
            model=value.get('model')
            self._model=model if isinstance(model,str) and 0<len(model)<=128 and not any(c in model for c in '\r\n') and (not self.settings.api_token or self.settings.api_token not in model) else None
            self._ready=True;self._checked=time.monotonic();self.last_code=None
            return self.status()
        except Exception:
            self._ready=False;self.last_code='GUIDED_VLA_SERVER_UNAVAILABLE'
            raise GuidedVLAError(self.last_code) from None

    def prepare_workflow(self,storage,job):
        self.require_validated_output(storage,job)
        try:
            if not job.scene or job.scene.primary_view!='F' or not job.mask or not job.mask.approved or not job.mask.approved_at or not job.rough3d:
                raise ValueError('Current approved F required')
            mask=storage.read_image('masks',job.mask.id)
            validate_binary_mask(mask,(job.scene.width,job.scene.height))
            if (job.rough3d.source_mask_id!=job.mask.id or job.rough3d.approved_at!=job.mask.approved_at
                    or job.rough3d.source_mask_sha256!=pixel_hash(mask)):raise ValueError('Rough mask differs')
            source=read_json(storage.artifact_path('native_context',job.id,'.scene.json'))
            record=read_json(storage.artifact_path('native_context',job.rough3d.artifact_id,'.rough3d.json'))
            if record['job_id']!=str(job.id) or record['mask_id']!=str(job.mask.id):raise ValueError('Wrong rough job')
            rough=NativeRough3DClient.load_saved(record['directory'],job.scene.sample_id)
            if any(sha256(rough.directory/name)!=h for name,h in record['files'].items()):raise ValueError('Rough changed')
            binding=NativeBinding(sample_id=job.scene.sample_id,camera='F',image=Path(source['images']['F']))
            split=resolve_split(source['dataset_root'],binding)
            if split['split']!=job.scene.split:raise ValueError('Split differs')
            markdown,direction=serialize_guidance(binding.sample_id,rough.image_guidance_2d,rough.plan)
            if rough.image_guidance_2d['image_size']!={'width':mask.width,'height':mask.height}:raise ValueError('Dimensions')
            components=detect_components(mask,job.mask.min_component_area)
            if len(components.regions)!=1:raise ValueError('Separate weld regions cannot be flattened')
            points=np.rint(rough.image_guidance_2d['segments'][0]['points_pixel']).astype(int)
            region=components.regions[0].region_id;labels=components.labels
            if sum(np.any(labels[max(0,y-2):y+3,max(0,x-2):x+3]==region) for x,y in points)/len(points)<.8:raise ValueError('Guidance mismatch')
            attempt=self.settings.attempts.resolve()/str(uuid4());attempt.mkdir(parents=True,exist_ok=False)
            (attempt/'masks').mkdir()
            # Immutable conditioning snapshot survives the later VLA_READY job
            # update; current input revision is separately rechecked before POST.
            write_json(attempt/'source_job.json',job.model_dump(mode='json'))
            write_bytes(attempt/'guidance.md',markdown.encode())
            mask_path=storage.artifact_path('masks',job.mask.id)
            write_bytes(attempt/'masks/F_mask.png',mask_path.read_bytes())
            names=('query_image_guidance_2d.json','reference_trajectory_3d.json')
            for name in names:write_bytes(attempt/name,(rough.directory/name).read_bytes())
            files={name:sha256(attempt/name) for name in ('guidance.md','masks/F_mask.png',*names)}
            manifest=dict(schema_version=1,workflow_request=True,attempt_id=attempt.name,endpoint=self.settings.endpoint,
                sample_id=job.scene.sample_id,split=job.scene.split,primary_camera='F',frame='mask_normalized:F',direction=direction,
                point_count=len(points),mask_views=['F'],files=files,workflow_job_id=str(job.id),
                workflow_conditioning_sha256=conditioning_hash(job),source_job=str(attempt/'source_job.json'),
                source_job_sha256=sha256(attempt/'source_job.json'),source_mask=str(mask_path),source_mask_id=str(job.mask.id),
                source_mask_sha256=sha256(mask_path),mask_pixels_sha256=pixel_hash(mask),mask_source=job.mask.mask_source,
                approved_at=job.mask.approved_at.isoformat(),
                native_source_artifact_id=str(job.mask.artifact.provenance.native_source_artifact_id) if job.mask.artifact else None,
                rough_session=str(rough.directory),rough_source_files=record['files'],split_resolution=split,
                reference_registered_to_query=False,reference_in_request=False,is_robot_executable=False,live_called=False,
                scene_source_sha256=source['hashes'],scene_normalized_sha256=source['normalized_hashes'])
            write_json(attempt/'request_manifest.json',manifest)
            self._manifest_hashes[attempt.name]=(sha256(attempt/'request_manifest.json'),storage)
            return attempt
        except (OSError,ValueError,KeyError,TypeError,GuidedVLAError):
            raise GuidedVLAError('GUIDED_VLA_GUIDANCE_INVALID') from None

    @staticmethod
    def require_validated_output(storage,job):
        from backend.model_clients.native_candidate import verify_snapshot,CandidateInvalid
        if job.native_output:
            if conditioning_hash(storage.get_job(job.id))!=conditioning_hash(job):
                raise GuidedVLAError('GUIDED_VLA_GUIDANCE_INVALID')
            if job.native_output.status!='NATIVE_OUTPUT_VALIDATED' or job.native_output.validation.status!='PASS':
                raise GuidedVLAError('GUIDED_VLA_GUIDANCE_INVALID')
            try:verify_snapshot(storage,job)
            except CandidateInvalid:raise GuidedVLAError('GUIDED_VLA_GUIDANCE_INVALID') from None

    def verify(self,attempt):
        attempt=Path(attempt).resolve()
        if attempt.name not in self._manifest_hashes:return super().verify(attempt)
        try:
            expected,storage=self._manifest_hashes[attempt.name]
            if attempt.parent!=self.settings.attempts.resolve() or sha256(attempt/'request_manifest.json')!=expected:raise ValueError('Manifest changed')
            manifest=read_json(attempt/'request_manifest.json');job=storage.get_job(UUID(manifest['workflow_job_id']))
            self.require_validated_output(storage,job)
            if conditioning_hash(job)!=manifest['workflow_conditioning_sha256']:raise ValueError('Workflow input changed')
            source=read_json(storage.artifact_path('native_context',job.id,'.scene.json'))
            if any(sha256(source['images'][v])!=h for v,h in manifest['scene_source_sha256'].items()):raise ValueError('Image changed')
            if any(sha256(storage.artifact_path('scenes',job.scene.views[v].image_id))!=h for v,h in manifest['scene_normalized_sha256'].items()):raise ValueError('Canvas image changed')
            binding=NativeBinding(sample_id=job.scene.sample_id,camera='F',image=Path(source['images']['F']))
            if resolve_split(source['dataset_root'],binding)!=manifest['split_resolution']:raise ValueError('Split changed')
            if sha256(attempt/'source_job.json')!=manifest['source_job_sha256']:raise ValueError('Snapshot changed')
            path=storage.artifact_path('masks',job.mask.id)
            if sha256(path)!=manifest['source_mask_sha256']:raise ValueError('Mask changed')
            package={name:(attempt/name).read_bytes() for name in manifest['files']}
            if any(digest(value)!=manifest['files'][name] for name,value in package.items()):raise ValueError('Package changed')
            if package['masks/F_mask.png']!=path.read_bytes():raise ValueError('F package differs')
            if any(sha256(Path(manifest['rough_session'])/name)!=h for name,h in manifest['rough_source_files'].items()):raise ValueError('Rough changed')
            return manifest,package
        except (OSError,ValueError,KeyError,TypeError,AttributeError,GuidedVLAError):
            raise GuidedVLAError('GUIDED_VLA_ATTEMPT_CHANGED') from None

    def run(self,storage,job):
        # Called only by the explicit user action/authorized semantic tool.
        self.require_validated_output(storage,job)
        self.check_server()
        attempt=self.prepare_workflow(storage,job)
        result=self.execute(attempt,live=True)  # Existing unchanged F-only writer.
        # Preserve base response/NPZ bytes. The documented health model is a
        # separate provenance record when the prediction response omits it.
        model=result.model or self._model
        write_json(attempt/'model_provenance.json',{'artifact_id':str(result.artifact_id),'model':model,
                   'source':'prediction_response' if result.model else 'documented_health_endpoint' if model else 'unavailable'})
        storage._write_json(storage.artifact_path('native_context',result.artifact_id,'.vla.json'),json.dumps({
            'attempt_id':attempt.name,'directory':str(attempt),'job_id':str(job.id),
            'files':{name:sha256(attempt/name) for name in ('request_manifest.json','source_job.json','submission.json',
                     'response.json','trajectory.npz','metadata.json','completion.json','model_provenance.json')}
        }))
        return VLAResultSummary(artifact_id=result.artifact_id,attempt_id=UUID(attempt.name),sample_id=result.sample_id,
            split=result.split,model=model,coordinate_frame=result.coordinate_frame,
            ade_mm=result.ade_mm,fde_mm=result.fde_mm,mask_views=['F'])
