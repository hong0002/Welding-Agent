"""Owned geometry-only Isaac viewport. No robot, physics, IK or scene alignment."""
import json
from pathlib import Path
import time
from uuid import UUID
from backend.services.current_preview_gate import read,resolve_command


def main(options):
    project=Path(__file__).resolve().parents[1];session=Path(options['session']).resolve()
    if session.parent!=project/'.cache/simulator/current-previews/sessions' or str(UUID(session.name))!=session.name:
        raise ValueError('Owned session required')
    resolve_command(read(session/'queue'/(str(UUID(options['first_request']))+'.json')),read(session/'catalog.json'))
    from isaacsim import SimulationApp
    app=SimulationApp(dict(headless=False,width=1280,height=960,renderer='RayTracedLighting',
        extra_args=['--/app/extensions/registryEnabled=false','--/log/file='+str(session/'kit.log')]))
    try:
        import numpy as np
        import omni.usd
        import omni.ui as ui
        from pxr import Gf,UsdGeom,UsdLux
        from isaacsim.core.utils.viewports import set_camera_view
        from omni.kit.viewport.utility import get_active_viewport,capture_viewport_to_file
        from backend.services.preview_visual_style import define_polyline
        from backend.services.preview_capture import CaptureDiagnostics
        window=ui.Window('Geometry Preview · simulation only',width=510,height=180)
        processed=set()
        print('[CURRENT_PREVIEW] READY '+session.name,flush=True)
        while app.is_running() and not (session/'stop.json').exists():
            app.update()
            pending=[p for p in sorted((session/'queue').glob('*.json')) if p.stem not in processed]
            if not pending:time.sleep(.02);continue
            request=pending[0];processed.add(request.stem)
            output=session/'outputs'/request.stem;output.mkdir(parents=True,exist_ok=False)
            result=session/'results'/(request.stem+'.json')
            try:
                d,value,_=resolve_command(read(request),read(session/'catalog.json'))
                if not d.get('geometry_only'):raise ValueError('Robot requests prohibited')
                omni.usd.get_context().new_stage();stage=omni.usd.get_context().get_stage()
                UsdGeom.SetStageMetersPerUnit(stage,1);UsdGeom.SetStageUpAxis(stage,UsdGeom.Tokens.z)
                UsdLux.DomeLight.Define(stage,'/Light').CreateIntensityAttr(1200)
                scale=.001 if value['units']=='mm' else 1
                runs=[np.asarray(run,dtype=float)*scale for run in value['runs']]
                points=np.vstack(runs);span=max(float(np.ptp(points,axis=0).max()),.02)
                color=(1.,.015,.025) if value['coordinate_frame']=='source_robot_frame_unaligned_with_isaac' else (1.,.18,.02)
                for i,run in enumerate(runs):
                    define_polyline(stage,'/Prediction/Run'+str(i),run,color,max(span*.007,.0005),usd_geom=UsdGeom,gf=Gf)
                relative='relative' in value['coordinate_frame']
                with window.frame:
                    with ui.VStack():
                        ui.Label('RELATIVE VISUALIZATION' if relative else 'RAW / UNVALIDATED GEOMETRY')
                        ui.Label(d['sample_id']+' · '+str(d['point_count'])+' points · independent finite runs')
                        ui.Label('Source frame only · no workpiece registration · robot blocked')
                        if value['units']=='unknown':ui.Label('UNKNOWN UNITS · arbitrary visualization units, not physical meters')
                        ui.Label('Physical execution disabled · no physics stepping')
                center=points.mean(axis=0);set_camera_view(eye=(center+np.array([1.4,-1.8,1.2])*span).tolist(),target=center.tolist())
                for _ in range(60):app.update()
                stage.GetRootLayer().Export(str(output/'scene.usda'))
                (output/'geometry.json').write_text(json.dumps(value,allow_nan=False),encoding='utf-8')
                diagnostics=CaptureDiagnostics(output,lambda *args,**kwargs:None,timeout=15)
                def capture(path):
                    viewport=get_active_viewport();viewport.set_texture_resolution((1280,960))
                    capture_viewport_to_file(viewport,path)
                diagnostics.attempt('path_detail',request_capture=capture,update=app.update)
                report=dict(state='done',job_id=d['job_id'],artifact_id=d['artifact_id'],package_id=d['package_id'],
                    sample_id=d['sample_id'],point_count=d['point_count'],exact_xyz_preserved=True,
                    fixture_ready=False,physical_robot_executable=False,robot_motion=False,physics_stepping=False,
                    geometry_only=True,source_frame=value['coordinate_frame'],**diagnostics.summary())
                for path in (output/'report.json',result):path.write_text(json.dumps(report,allow_nan=False),encoding='utf-8')
                print('[CURRENT_PREVIEW] DONE geometry-only; robot=false physics=false',flush=True)
            except Exception as exc:
                result.write_text(json.dumps(dict(state='failed',phase='geometry',exception_class=type(exc).__name__)),encoding='utf-8')
                print('[CURRENT_PREVIEW] FAILED geometry '+type(exc).__name__,flush=True)
    finally:app.close()
