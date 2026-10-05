"""Owned, immutable XYZ display package. No IK, GT substitution or robot admission."""
import json
from pathlib import Path
from uuid import UUID,uuid4
from backend.services.current_preview_gate import sha,read

CODE=('backend/services/geometry_preview.py','backend/geometry_isaac_preview.py',
      'backend/services/current_preview_gate.py','backend/services/preview_visual_style.py')


def verify(d,path,project):
    """Stdlib-only child gate; display identity/hashes remain strict."""
    import math,hashlib
    if (d['preview_id']!=path.parent.name or d['kind']!='path' or not d['geometry_only']
            or d['physical_robot_executable'] is not False or d['robot_ready'] is not False
            or d['vla_orientation'] is not False):raise ValueError('Geometry-only contract')
    package=Path(d['package']).resolve()
    if package!=path.parent/'geometry.json' or sha(package)!=d['package_sha256']:raise ValueError('Geometry changed')
    value=read(package)
    if not value['runs'] or value['units'] not in ('mm','m','unknown') or any(
        len(p)!=3 or not all(type(v) in (int,float) and math.isfinite(v) for v in p)
        for run in value['runs'] for p in run):raise ValueError('No finite geometry')
    if sum(map(len,value['runs']))!=d['point_count']:raise ValueError('Point count')
    job_file=Path(d['job_file']).resolve()
    if not job_file.is_relative_to(project) or job_file.name!=d['job_id']+'.json':raise ValueError('Job binding')
    job=read(job_file);raw=job.get('raw_final_prediction') or {}
    if d.get('schema_version')=='geometry-preview-v2':
        source=Path(d['source_display']).resolve()
        if (source!=path.parent/'source-display.json' or sha(source)!=d['source_sha256']
                or d.get('isolated_only') is not True or job['id']!=d['job_id']):
            raise ValueError('Isolated display binding')
        snapshot=read(source)
        if (snapshot['job_id']!=d['job_id'] or snapshot['artifact_id']!=d['artifact_id']
                or snapshot['sample_id']!=d['sample_id'] or snapshot['geometry']!=value):
            raise ValueError('Display snapshot changed')
        if set(d['owned_code'])!=set(CODE) or any(sha(project/n)!=h for n,h in d['owned_code'].items()):
            raise ValueError('Owned renderer changed')
        return d,value,package
    conditioning={k:job[k] for k in ('scene','mask','instruction','rough_mode','rough3d','rough_trajectory')}
    if job.get('native_output') is not None:conditioning['native_output']=job['native_output']
    digest=hashlib.sha256(json.dumps(conditioning,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    if (raw.get('artifact_id')!=d['artifact_id'] or job['scene']['sample_id']!=d['sample_id']
            or digest!=d['job_conditioning_sha256']):raise ValueError('Current result stale')
    source=Path(d['source_display']).resolve()
    namespace='gpt2-trajectory' if raw.get('source')=='vlm_final_gpt2' else 'gpt-trajectory'
    if not source.is_relative_to(project/'.cache/native-models'/namespace) or sha(source)!=d['source_sha256']:
        raise ValueError('Source changed')
    if set(d['owned_code'])!=set(CODE) or any(sha(project/n)!=h for n,h in d['owned_code'].items()):
        raise ValueError('Owned renderer changed')
    return d,value,package


class GeometryPreviewService:
    def __init__(self,workflow,runtime,*,project=None):
        self.workflow,self.runtime=workflow,runtime
        self.project=Path(project or Path(__file__).resolve().parents[2]).resolve()

    def prepare(self,job_id):
        from backend.services.current_preview_config import CurrentPreviewError
        from backend.model_clients.guided_workflow import conditioning_hash
        job=self.workflow.get_display_job(job_id);raw=job.raw_final_prediction
        if not raw or not raw.displayable:raise CurrentPreviewError('GEOMETRY_OUTPUT_MISSING','표시할 XYZ 결과가 없습니다.',409)
        data=self.workflow.final_predictor.read_display(self.workflow.storage,job,raw.artifact_id)
        if data.get('stale') or not data.get('current_overlay_allowed',True):
            raise CurrentPreviewError('GEOMETRY_OUTPUT_STALE','이전 또는 다른 샘플 결과는 별도 viewer에서 확인하세요.',409)
        if data['units'] not in ('mm','m'):raise CurrentPreviewError('GEOMETRY_UNITS_UNKNOWN','좌표 단위를 확인할 수 없습니다. 웹 raw viewer를 사용하세요.',409)
        project=self.project
        folder=project/'.cache/simulator/current-previews/packages'/str(uuid4());folder.mkdir(parents=True,exist_ok=False)
        value={k:data[k] for k in ('runs','coordinate_frame','units')}
        (folder/'geometry.json').write_text(json.dumps(value,allow_nan=False),encoding='utf-8')
        source=self.workflow.final_predictor.settings.attempts.resolve()/str(raw.attempt_id)/'display.json'
        d=dict(schema_version='geometry-preview-v1',preview_id=folder.name,package_id=folder.name,
            job_id=str(job.id),artifact_id=str(raw.artifact_id),sample_id=job.scene.sample_id,
            package=str(folder/'geometry.json'),package_sha256=sha(folder/'geometry.json'),
            source_display=str(source),source_sha256=sha(source),job_file=str(self.workflow.storage.artifact_path('jobs',job.id,'.json')),
            job_conditioning_sha256=conditioning_hash(job),simulator_root=str(self.runtime.config.root),
            backend=self.runtime.backend,family=job.scene.sample_id.split('_')[0],kind='path',geometry_only=True,
            point_count=sum(map(len,data['runs'])),playback_point_count=None,mode='GEOMETRY_VISUALIZATION_ONLY',
            coordinate_frame=data['coordinate_frame'],ade_mm=None,fde_mm=None,fixture_ready=False,
            physical_robot_executable=False,validated_simulation=False,robot_ready=False,vla_orientation=False,
            orientation_source='simulator_policy',clearance_warning='UNVALIDATED_GEOMETRY',
            owned_code={n:sha(project/n) for n in CODE})
        (folder/'preview.json').write_text(json.dumps(d,allow_nan=False),encoding='utf-8')
        claim=dict(path=str(folder/'preview.json'),sha256=sha(folder/'preview.json'))
        verify(d,folder/'preview.json',project)
        return claim

    def run(self,job_id):
        self.runtime.check_configuration(kind='path')
        return self.runtime.submit(self.prepare_display(job_id))

    def prepare_display(self,job_id,artifact=None,stage_index=None,output_kind=None):
        from backend.services.output_catalog import xyz_output
        from backend.services.current_preview_config import CurrentPreviewError
        job=self.workflow.get_display_job(job_id)
        try:row=xyz_output(self.workflow.storage,job,self.workflow.final_predictor,artifact,stage_index,project=self.project,output_kind=output_kind)
        except ValueError:raise CurrentPreviewError('GEOMETRY_OUTPUT_MISSING','표시할 숫자 XYZ가 없습니다.',409) from None
        folder=self.project/'.cache/simulator/current-previews/packages'/str(uuid4());folder.mkdir(parents=True,exist_ok=False)
        value=dict(runs=row['runs'],coordinate_frame=row.get('coordinate_frame','unknown'),units=row.get('units','unknown'))
        sample=row.get('sample_id') or job.scene.sample_id
        snapshot=dict(job_id=str(job.id),artifact_id=row['id'],sample_id=sample,geometry=value,
            stale=row['stale'],label=row['label'],stage_index=row.get('stage_index'))
        for name,data in [('geometry.json',value),('source-display.json',snapshot)]:
            (folder/name).write_text(json.dumps(data,allow_nan=False),encoding='utf-8')
        d=dict(schema_version='geometry-preview-v2',preview_id=folder.name,package_id=folder.name,
            job_id=str(job.id),artifact_id=row['id'],sample_id=sample,isolated_only=True,
            package=str(folder/'geometry.json'),package_sha256=sha(folder/'geometry.json'),
            source_display=str(folder/'source-display.json'),source_sha256=sha(folder/'source-display.json'),
            job_file=str(self.workflow.storage.artifact_path('jobs',job.id,'.json')),
            simulator_root=str(self.runtime.config.root),backend=self.runtime.backend,family=sample.split('_')[0],kind='path',geometry_only=True,
            point_count=sum(map(len,value['runs'])),playback_point_count=None,mode='GEOMETRY_VISUALIZATION_ONLY',
            coordinate_frame=value['coordinate_frame'],ade_mm=None,fde_mm=None,fixture_ready=False,
            physical_robot_executable=False,validated_simulation=False,robot_ready=False,vla_orientation=False,
            orientation_source='simulator_policy',clearance_warning='UNVALIDATED_GEOMETRY',
            owned_code={n:sha(self.project/n) for n in CODE})
        (folder/'preview.json').write_text(json.dumps(d,allow_nan=False),encoding='utf-8')
        verify(d,folder/'preview.json',self.project)
        return dict(path=str(folder/'preview.json'),sha256=sha(folder/'preview.json'))
