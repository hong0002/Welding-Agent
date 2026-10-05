"""Source-preserving robot display. Strict authority is never granted by a demo."""
import json
import os
import subprocess
from pathlib import Path
from uuid import UUID, uuid4
from backend.services.current_preview_gate import read,sha

CODE=('backend/services/robot_demo.py','backend/demo_robot_prepare.py','backend/demo_robot_isaac_preview.py',
      'backend/services/current_preview_gate.py','backend/services/preview_visual_style.py','backend/services/preview_mesh.py',
      'backend/services/prediction_path_evidence.py','backend/services/sample_scene.py','backend/services/preview_environment.py')


def verify(d,path,project):
    import math
    if (d['preview_id']!=path.parent.name or d['kind']!='robot' or d['robot_demo_only'] is not True
            or d['demo_transformed'] is not True or d['source_preserved'] is not True
            or d['physical_robot_executable'] is not False or d['physical_execution'] is not False
            or d['vla_orientation'] is not False or d['validated_simulation'] is not False):raise ValueError('Demo flags')
    for name,key in [('geometry.json','package_sha256'),('source-display.json','source_sha256'),('demo_playback.npz','playback_sha256'),('demo_mapping.json','mapping_sha256')]:
        if sha(path.parent/name)!=d[key]:raise ValueError('Demo snapshot changed')
    source=read(path.parent/'source-display.json');geometry=read(path.parent/'geometry.json')
    if (source['job_id']!=d['job_id'] or source['artifact_id']!=d['artifact_id'] or source['sample_id']!=d['sample_id']
            or source['geometry']!=geometry or sum(map(len,geometry['runs']))!=d['point_count']
            or any(len(p)!=3 or not all(type(x) in (int,float) and math.isfinite(x) for x in p) for r in geometry['runs'] for p in r)):
        raise ValueError('Demo source identity')
    job_file=Path(d['job_file']).resolve()
    if not job_file.is_relative_to(project) or job_file.name!=d['job_id']+'.json' or read(job_file)['id']!=d['job_id']:raise ValueError('Demo job')
    if set(d['owned_code'])!=set(CODE) or any(sha(project/n)!=h for n,h in d['owned_code'].items()):raise ValueError('Demo renderer changed')
    root=Path(d['simulator_root']).resolve()
    if any(not (root/n).resolve().is_relative_to(root) or sha(root/n)!=h for n,h in d['native_files'].items()):raise ValueError('Demo assets changed')
    if d['package']!=str(path.parent/'geometry.json') or d['playback_point_count']<2:raise ValueError('Demo package')
    # Full-scene additions use the existing immutable snapshot checks, not a new
    # readiness/approval policy. Historical simplified packages remain evidence.
    for name,digest in d.get('scene_files',{}).items():
        if sha(path.parent/name)!=digest:raise ValueError('Demo scene snapshot changed')
    if d.get('sample_scene'):
        for name in ('h5','obj'):
            if sha(d['sample_scene'][name])!=d['sample_scene'][name+'_sha256']:raise ValueError('Demo sample asset changed')
    return d,geometry,path.parent/'demo_playback.npz'


def successful_anchor(project,root):
    """Bounded owned successful robot evidence, never a guessed seed coordinate."""
    sessions=project/'.cache/simulator/current-previews/sessions'
    reports=list(sessions.glob('*/outputs/*/report.json'))[-500:]
    for file in sorted(reports,key=lambda p:p.stat().st_mtime,reverse=True):
        try:
            r=read(file)
            if not (r.get('state')=='done' and r.get('robot_motion') is True and r.get('backend') in {'dataset_stp','dataset_final'} and not r.get('robot_demo_only')):continue
            p=project/'.cache/simulator/prediction-packages'/r['package_id']
            package=read(p/'package.json')
            claim=read(file.parents[2]/'catalog.json')[r['artifact_id']]
            descriptor_path=Path(claim['path']).resolve()
            if not descriptor_path.is_relative_to(project/'.cache/simulator/current-previews/packages') or sha(descriptor_path)!=claim['sha256']:continue
            descriptor=read(descriptor_path)
            if Path(descriptor['simulator_root']).resolve()!=root or descriptor['package_id']!=r['package_id']:continue
            solution=p/'native/trajectory_solution.npz'
            if solution.is_file() and sha(solution)==descriptor['native_files']['trajectory_solution.npz']:return solution,file
        except (OSError,ValueError,KeyError,TypeError):continue
    from backend.services.current_preview_config import CurrentPreviewError
    raise CurrentPreviewError('ROBOT_DEMO_ANCHOR_MISSING','성공한 RB10 preview pose 증거가 없습니다.',503)


class RobotPreview:
    def __init__(self,workflow,runtime,scene_preview,*,project=None,prepare=None):
        self.workflow,self.runtime,self.scene_preview=workflow,runtime,scene_preview
        self.project=Path(project or Path(__file__).resolve().parents[2]).resolve();self.prepare=prepare or self._prepare

    def _prepare(self,folder,root):
        from backend.model_clients.native import NATIVE_PYTHON
        from backend.services.current_preview_config import CurrentPreviewError
        anchor,evidence=successful_anchor(self.project,root)
        options=dict(root=str(root),output=str(folder),anchor_solution=str(anchor))
        if self.runtime.backend in {'dataset_stp','dataset_v2','dataset_final'}:
            from backend.services.simulator_prediction_package import PackageSettings
            from backend.services.simulator2_contract import exact_assets
            settings=getattr(self.scene_preview,'settings',None) or PackageSettings.from_env()
            sample=read(folder/'source-display.json')['sample_id']
            h5,obj=exact_assets(settings.dataset_root,sample)
            options.update(h5=str(h5),obj=str(obj),sample_id=sample,backend=self.runtime.backend)
        env={k:v for k,v in os.environ.items() if not any(w in k.upper() for w in ('SECRET','TOKEN','API_KEY'))}
        env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
        try:
            p=subprocess.run([str(NATIVE_PYTHON),'-B','-X','utf8',str(self.project/'backend/demo_robot_prepare.py')],
                input=json.dumps(options),
                cwd=self.project,env=env,shell=False,capture_output=True,text=True,encoding='utf-8',timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            value=json.loads(p.stdout) if p.returncode==0 else {}
        except (OSError,ValueError,subprocess.SubprocessError):value={}
        if value.get('ok') is not True:raise CurrentPreviewError('ROBOT_DEMO_IK_UNAVAILABLE','Demo IK를 완료하지 못했습니다. 원본 경로는 viewer에서 확인할 수 있습니다.',409)
        value.update(anchor_evidence=str(evidence),anchor_evidence_sha256=sha(evidence),anchor_solution_sha256=sha(anchor))
        return value

    def run(self,job_id,artifact=None,stage_index=None,output_kind=None):
        from backend.services.current_preview_config import CurrentPreviewError
        from backend.services.output_catalog import xyz_output
        job=self.workflow.get_display_job(job_id)
        try:row=xyz_output(self.workflow.storage,job,self.workflow.final_predictor,artifact,stage_index,project=self.project,output_kind=output_kind)
        except ValueError:raise CurrentPreviewError('ROBOT_DEMO_GEOMETRY_MISSING','2점 이상의 3D 결과를 선택하세요.',409) from None
        if sum(map(len,row['runs']))<2:raise CurrentPreviewError('ROBOT_DEMO_GEOMETRY_MISSING','2점 이상의 3D 결과가 필요합니다.',409)
        if row['stale'] or row.get('sample_id')!=job.scene.sample_id or row.get('stage') in {'playback','simulator_source'}:
            raise CurrentPreviewError('CURRENT_PREDICTION_REQUIRED','현재 sample의 모델 prediction을 선택하세요. 이전 결과는 source viewer에서 확인할 수 있습니다.',409)
        if (row['coordinate_frame']=='source_robot_frame_unaligned_with_isaac'
                and row.get('sample_id')==job.scene.sample_id and not row['stale']):
            # The native client prepares IK when needed. A missing cached preflight
            # is not a reason to scale an absolute source into a demo workspace.
            # Native failures remain strict failures; never silently remap them.
            self.scene_preview.run(job_id=job.id,artifact_id=UUID(row['id']),kind='robot',selected_source=row)
            return dict(mode='STRICT',artifact_id=row['id'])
        if getattr(self.scene_preview,'backend',None)=='dataset_final':
            return self.scene_preview.run_demo(preview=self,job=job,selected_source=row)
        return self._run_demo(job,row)

    def _run_demo(self,job,row):
        """Explicit relative/raw visualization, never fallback from a strict failure."""
        from backend.services.geometry_preview import GeometryPreviewService
        self.runtime.check_configuration(kind='robot')
        claim=GeometryPreviewService(self.workflow,self.runtime,project=self.project).prepare_display(job.id,row['id'],row.get('stage_index'),row['stage'])
        path=Path(claim['path']);d=read(path);folder=path.parent;root=self.runtime.config.root.resolve()
        mapping=self.prepare(folder,root)
        (folder/'demo_mapping.json').write_text(json.dumps(mapping,allow_nan=False),encoding='utf-8')
        import xml.etree.ElementTree as ET
        names={'prepare_rb5_h5_trajectory.py','welding_tool_geometry.py','rbpodo_description/robots/rb10_1300e_u.urdf','ATU01035_welding_tool.usd'}
        if mapping.get('sample_scene'):
            if self.runtime.backend=='dataset_final':
                from backend.services.simulator_final_contract import NATIVE_FILES
            else:
                from backend.services.simulator2_contract import NATIVE_FILES
            names.update(NATIVE_FILES)
            if self.runtime.backend in {'dataset_stp','dataset_final'}:names.add('welding_environment.py')
        tree=ET.parse(root/'rbpodo_description/robots/rb10_1300e_u.urdf')
        names.update(m.attrib['filename'].removeprefix('package://') for m in tree.findall('.//mesh'))
        from backend.services.prediction_path_evidence import xyz_hash
        d.update(prediction_selection=dict(artifact_id=row['id'],output_kind=row['stage'],stage_index=row.get('stage_index'),
            label=row['label'],coordinate_frame=row['coordinate_frame'],units=row['units'],source_point_count=d['point_count'],
            source_xyz_sha256=xyz_hash([p for r in row['runs'] for p in r])),
            schema_version='robot-demo-preview-v1',kind='robot',geometry_only=False,isolated_only=True,
            family='_'.join(d['sample_id'].split('_')[:2]),
            robot_demo_only=True,demo_transformed=True,source_preserved=True,physical_execution=False,
            prediction_source=row.get('source','vlm_final_gpt' if row['stage'] in {'final','gpt_stage'} else 'guided_vla'),
            prediction_stage=row['label'],demo_parent_hash=xyz_hash([p for r in row['runs'] for p in r]),
            demo_transform=dict(translation_m=mapping['anchor_tcp_m'],uniform_scale=mapping['uniform_scale'],
                rotation='identity',source_origin='first prediction point'),demo_point_count=mapping['playback_point_count'],
            mode='ROBOT_DEMO_VISUALIZATION_ONLY',clearance_warning='SOURCE_TRAJECTORY_TRANSFORMED',
            playback_point_count=mapping['playback_point_count'],playback_sha256=sha(folder/'demo_playback.npz'),
            mapping_sha256=sha(folder/'demo_mapping.json'),orientation_source=mapping['orientation_source'],
            sample_scene=mapping.get('sample_scene'),scene_mode='CURRENT_SAMPLE_STP' if mapping.get('sample_scene') and self.runtime.backend in {'dataset_stp','dataset_final'} else None,
            scene_files={n:sha(folder/n) for n in ('sample_scene.npz','sample_scene.json')} if mapping.get('sample_scene') else {},
            owned_code={n:sha(self.project/n) for n in CODE},native_files={n:sha(root/n) for n in sorted(names)})
        path.write_text(json.dumps(d,allow_nan=False),encoding='utf-8');verify(d,path,self.project)
        self.runtime.submit(dict(path=str(path),sha256=sha(path)))
        return dict(mode='DEMO',artifact_id=row['id'],demo_transformed=True,source_preserved=True,robot_demo_only=True,physical_execution=False)
