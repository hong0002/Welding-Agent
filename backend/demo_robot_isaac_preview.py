"""Owned RB10 joint/FK animation in the current native sample scene; no hardware."""
import json
import time
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from backend.services.current_preview_gate import read,resolve_command


def main(options):
    from uuid import UUID
    project=Path(__file__).resolve().parents[1];session=Path(options['session']).resolve()
    if session.parent!=project/'.cache/simulator/current-previews/sessions' or str(UUID(session.name))!=session.name:raise ValueError('Owned session required')
    request=session/'queue'/(str(UUID(options['first_request']))+'.json')
    d,source,npz=resolve_command(read(request),read(session/'catalog.json'))
    from isaacsim import SimulationApp
    app=SimulationApp({'headless':False,'width':1280,'height':960,'renderer':'RayTracedLighting',
        'extra_args':['--/log/file='+str(session/'kit.log'),'--/app/userConfigPath='+str(session/'user.config.json'),'--/app/extensions/registryEnabled=false']})
    live=None
    try:
        import numpy as np
        from scipy.spatial.transform import Rotation
        import omni.usd
        import omni.ui as ui
        from isaacsim.core.utils.viewports import set_camera_view
        from omni.kit.viewport.utility import get_active_viewport,capture_viewport_to_file
        from pxr import Gf,UsdGeom,UsdLux,UsdPhysics,Sdf,Usd
        from backend.services.preview_visual_style import define_polyline
        from backend.services.preview_mesh import load_visual_mesh
        from backend.services.preview_live_producer import LiveFrameProducer
        from backend.services.preview_capture import CaptureDiagnostics
        sim=Path(d['simulator_root']);sys.path.insert(0,str(sim))
        from prepare_rb5_h5_trajectory import matrix_from_xyz_rpy,JOINT_NAMES
        def log(text):print('[CURRENT_PREVIEW] '+text,flush=True)
        def update():
            app.update()
            if live:live.pump(live_capture)
        def live_capture(callback):
            from omni.kit.viewport.utility import capture_viewport_to_buffer
            viewport=get_active_viewport();viewport.set_texture_resolution((1280,720))
            def received(buffer,size,width,height,fmt):callback(buffer,size,width,height,fmt)
            return capture_viewport_to_buffer(viewport,received)
        output=session/'outputs'/request.stem;output.mkdir(parents=True,exist_ok=False)
        result=session/'results'/(request.stem+'.json')
        with np.load(npz,allow_pickle=False) as data:arrays={k:data[k].copy() for k in data.files}
        from backend.services.prediction_path_evidence import verify_demo_source
        proof=verify_demo_source(source,arrays,read(npz.parent/'demo_mapping.json'))
        if d['prediction_selection']['source_xyz_sha256']!=proof['source_xyz_sha256']:raise ValueError('Demo source changed')
        joints=arrays['joint_position_rad'];targets=arrays['demo_playback_points']
        if joints.shape!=(len(targets),6) or len(targets)<2 or not np.isfinite(joints).all():raise ValueError('Demo joint evidence')
        omni.usd.get_context().new_stage();stage=omni.usd.get_context().get_stage()
        UsdGeom.SetStageUpAxis(stage,'Z');UsdGeom.SetStageMetersPerUnit(stage,1.)
        stage.SetMetadata('customLayerData',{'mode':d['mode'],'artifact_id':d['artifact_id'],'robot_demo_only':True,'physical_execution':False})
        light=UsdLux.DomeLight.Define(stage,'/Light');light.CreateIntensityAttr(1800.)
        from backend.services.sample_scene import render_sample_scene,scene_composition,sample_camera
        full_scene=bool(d.get('sample_scene'))
        if full_scene:
            with np.load(npz.parent/'sample_scene.npz',allow_pickle=False) as data:
                scene_arrays={k:data[k].copy() for k in data.files}
            work=render_sample_scene(stage,scene_arrays,backend=d['backend'],usd_geom=UsdGeom,gf=Gf)
        base=UsdGeom.Xform.Define(stage,'/RB10');UsdPhysics.ArticulationRootAPI.Apply(base.GetPrim())
        tree=ET.parse(sim/'rbpodo_description/robots/rb10_1300e_u.urdf').getroot();ops={};joint_prims={}
        for link in tree.findall('link'):
            name=link.attrib['name'];x=UsdGeom.Xform.Define(stage,'/RB10/'+name);ops[name]=x.AddTransformOp()
            body=UsdPhysics.RigidBodyAPI.Apply(x.GetPrim());body.CreateKinematicEnabledAttr(True)
            for index,visual in enumerate(link.findall('visual')):
                asset=visual.find('geometry/mesh')
                if asset is None:continue
                path=(sim/asset.attrib['filename'].removeprefix('package://')).resolve()
                if not path.is_relative_to(sim):raise ValueError('Robot asset containment')
                verts,counts,indices=load_visual_mesh(path);verts*=np.fromstring(asset.attrib.get('scale','1 1 1'),sep=' ')
                origin=visual.find('origin')
                if origin is not None:
                    mat=matrix_from_xyz_rpy(np.fromstring(origin.attrib.get('xyz','0 0 0'),sep=' '),np.fromstring(origin.attrib.get('rpy','0 0 0'),sep=' '))
                    verts=verts@mat[:3,:3].T+mat[:3,3]
                mesh=UsdGeom.Mesh.Define(stage,f'/RB10/{name}/Visual{index}')
                mesh.CreatePointsAttr([Gf.Vec3f(*map(float,p)) for p in verts]);mesh.CreateFaceVertexCountsAttr(counts);mesh.CreateFaceVertexIndicesAttr(indices)
                mesh.CreateSubdivisionSchemeAttr('none');mesh.CreateDisplayColorAttr([Gf.Vec3f(.42,.63,.78)])
        for name in JOINT_NAMES:
            spec=next(j for j in tree.findall('joint') if j.attrib['name']==name)
            joint=UsdPhysics.RevoluteJoint.Define(stage,'/RB10/Joints/'+name)
            joint.CreateBody0Rel().SetTargets([Sdf.Path('/RB10/'+spec.find('parent').attrib['link'])])
            joint.CreateBody1Rel().SetTargets([Sdf.Path('/RB10/'+spec.find('child').attrib['link'])])
            # URDF FK is the animation authority; drives document the actual six joint angles.
            joint_prims[name]=UsdPhysics.DriveAPI.Apply(joint.GetPrim(),'angular').CreateTargetPositionAttr()
        tool=UsdGeom.Xform.Define(stage,'/Tool').AddTransformOp()
        geo=UsdGeom.Xform.Define(stage,'/Tool/Geometry');geo.GetPrim().GetReferences().AddReference(str(sim/'ATU01035_welding_tool.usd'));geo.AddScaleOp().Set(Gf.Vec3f(.001,.001,.001))
        rendered=[]
        for i,(begin,end) in enumerate(arrays['run_bounds']):
            curve=define_polyline(stage,'/DemoPlayback'+str(i),targets[begin:end],(1.,.04,.04),.004,usd_geom=UsdGeom,gf=Gf)
            if end-begin>=2:rendered.extend(curve.GetPointsAttr().Get())
            elif end>begin:rendered.extend(targets[begin:end])
        rendered=np.asarray(rendered,dtype=float)
        if rendered.shape!=targets.shape or not np.allclose(rendered,targets,atol=2e-7,rtol=0):raise ValueError('Demo red path differs')
        center=targets.mean(0)
        if full_scene:set_camera_view(**sample_camera())
        else:set_camera_view(eye=(center+[-1.2,-1.5,.95]).tolist(),target=[.45,0,.35])
        window=ui.Window('ROBOT DEMO · VISUALIZATION ONLY',width=540,height=220)
        with window.frame:
            with ui.VStack():
                ui.Label('ROBOT DEMO · VISUALIZATION ONLY')
                ui.Label('SOURCE TRAJECTORY TRANSFORMED · NOT ROBOT-EXECUTABLE')
                if full_scene:ui.Label('CURRENT SAMPLE · STP · Exact Sample OBJ · GT PATH NOT USED FOR ROBOT PLAYBACK')
                ui.Label('Actual RB10 six joint FK animation · physics=false')
                ui.Label(d['sample_id']+f' · source {d["point_count"]} / demo {len(targets)} points')
                label=ui.Label('Preparing demo')
        diagnostics=CaptureDiagnostics(output,lambda *a,**k:None,timeout=15)
        def capture(name):
            def request_capture(path):
                viewport=get_active_viewport();viewport.set_texture_resolution((1280,960))
                capture_viewport_to_file(viewport,path)
            diagnostics.attempt(name,request_capture=request_capture,update=update)
        log('READY '+session.name)
        live=LiveFrameProducer(output,dict(job_id=d['job_id'],artifact_id=d['artifact_id'],session_id=session.name,request_id=request.stem))
        measured=[];angles=[];link_samples=[]
        def apply(q,frame):
            links={'link0':np.eye(4)}
            for index,name in enumerate((*JOINT_NAMES,'tcp_joint')):
                j=next(v for v in tree.findall('joint') if v.attrib['name']==name);o=j.find('origin')
                local=matrix_from_xyz_rpy(np.fromstring(o.attrib.get('xyz','0 0 0'),sep=' '),np.fromstring(o.attrib.get('rpy','0 0 0'),sep=' '));rot=np.eye(4)
                if j.attrib['type']!='fixed':rot[:3,:3]=Rotation.from_rotvec(np.fromstring(j.find('axis').attrib['xyz'],sep=' ')*q[index]).as_matrix()
                links[j.find('child').attrib['link']]=links[j.find('parent').attrib['link']]@local@rot
            for name,op in ops.items():
                value=Gf.Matrix4d(links[name].T.tolist());op.Set(value);op.Set(value,Usd.TimeCode(frame))
            for index,name in enumerate(JOINT_NAMES):
                joint_prims[name].Set(float(np.rad2deg(q[index])));joint_prims[name].Set(float(np.rad2deg(q[index])),Usd.TimeCode(frame))
            tool.Set(Gf.Matrix4d((links['tcp']@arrays['cad_to_robot_tcp']).T.tolist()))
            return (links['tcp']@arrays['urdf_tcp_to_weld_tcp'])[:3,3],links['tcp'].tolist()
        previous=joints[0]
        for index,q in enumerate(joints):
            if (session/'stop.json').exists():return
            # Independent runs are not joined into a welding polyline.
            starts={int(a) for a,b in arrays['run_bounds']}
            if index in starts:previous=q
            for alpha in np.linspace(0,1,18):apply(previous+(q-previous)*alpha,index);update()
            tip,link=apply(q,index);measured.append(tip);angles.append(q.tolist());link_samples.append(link)
            label.text=f'RB10 demo waypoint {index+1}/{len(joints)}';previous=q
            log(f'DEMO_WAYPOINT {index} rb10_joints=true physics=false')
            if index==0:capture('P0')
            if index==len(joints)//2:capture('P4')
        capture('P8');capture('path_detail');live.close();live=None
        stage.GetRootLayer().Export(str(output/'scene.usda'))
        (output/'geometry.json').write_text(json.dumps(source,allow_nan=False),encoding='utf-8')
        np.savez_compressed(output/'waypoints.npz',demo_playback_points=targets,joint_position_rad=angles,measured_tip_world_m=measured,source_indices=arrays['source_indices'],run_bounds=arrays['run_bounds'],rendered_path_world_m=rendered)
        motion=float(np.abs(np.diff(angles,axis=0)).max())>1e-7
        report=dict(state='done',job_id=d['job_id'],artifact_id=d['artifact_id'],package_id=d['package_id'],sample_id=d['sample_id'],
            scene_composition=scene_composition(stage,'/DemoPlayback0',backend=d['backend']),
            scene_mode=d.get('scene_mode'),sample_scene=d.get('sample_scene'),
            prediction_selection=d['prediction_selection'],renderer_source_point_count=len(rendered),**proof,
            point_count=d['point_count'],source_point_count=d['point_count'],playback_point_count=len(joints),kind='robot',mode=d['mode'],backend=d['backend'],sample_family=d['family'],
            robot_motion=motion,rb10_joints_moved=motion,articulation_mode='kinematic URDF FK; six USD revolute joint targets animated',
            joint_delta_rad_max=float(np.abs(np.diff(angles,axis=0)).max()),link_tcp_transforms=link_samples,
            tip_error_mm_max=float(np.linalg.norm(np.asarray(measured)-targets,axis=1).max()*1000),
            exact_xyz_preserved=read(output/'geometry.json')==source,source_preserved=True,demo_transformed=True,robot_demo_only=True,
            physical_execution=False,physical_robot_executable=False,fixture_ready=False,validated_simulation=False,
            physics_stepping=False,vla_orientation=False,orientation_source=d['orientation_source'],playback_derived=True,
            playback_status='SUCCEEDED',**diagnostics.summary())
        for file in (output/'report.json',result):file.write_text(json.dumps(report,allow_nan=False),encoding='utf-8')
        log('DONE ROBOT_DEMO rb10_joints=true source_preserved=true physical=false')
        while app.is_running() and not (session/'stop.json').exists():app.update();time.sleep(.02)
    finally:
        if live:live.close()
        app.close()
