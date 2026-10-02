"""Owned Isaac GUI renderer for unchanged current VLA XYZ; no physics/timeline.

RB10 is a kinematic visual of the native URDF meshes, not an articulation
controller. Nine native IK/FK poses are shown without target interpolation.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import time
import xml.etree.ElementTree as ET
from uuid import UUID

from backend.services.current_preview_gate import read, resolve_command, sha
from backend.services.preview_capture import CaptureDiagnostics, play_waypoints


def main(options):
    project = Path(__file__).resolve().parents[1]
    session = Path(options['session']).resolve()
    if (session.parent != project / '.cache/simulator/current-previews/sessions' or
            str(UUID(session.name)) != session.name):
        raise ValueError('Preview session is not backend-owned')
    first = session / 'queue' / (str(UUID(options['first_request']))+'.json')
    # Hash/identity recheck precedes SimulationApp. Nothing downloaded or inferred.
    resolve_command(read(first), read(session / 'catalog.json'))
    from isaacsim import SimulationApp
    app = SimulationApp({'headless': False, 'width': 1280, 'height': 960, 'renderer': 'RayTracedLighting',
        'extra_args': ['--/log/file='+str(session/'kit.log'),
                       '--/app/userConfigPath='+str(session/'user.config.json'),
                       '--/app/extensions/registryEnabled=false']})
    try:
        import numpy as np
        from scipy.spatial.transform import Rotation
        import omni.usd
        import omni.ui as ui
        from isaacsim.core.utils.viewports import set_camera_view
        from omni.kit.viewport.utility import get_active_viewport, capture_viewport_to_file
        from pxr import Gf, Usd, UsdGeom, UsdLux
        from backend.services.preview_mesh import load_visual_mesh

        def log(value):
            print('[CURRENT_PREVIEW] '+value, flush=True)

        def event(stage, **details):
            entry = dict(at=datetime.now(timezone.utc).isoformat(), stage=stage, **details)
            with (session/'stages.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(entry, allow_nan=False)+'\n')
            log(json.dumps(entry, allow_nan=False))

        def save(path, value):
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')
            temporary.replace(path)

        def matrix_op(stage, path):
            return UsdGeom.Xform.Define(stage, path).AddTransformOp()

        def set_matrix(op, matrix):
            op.Set(Gf.Matrix4d(np.asarray(matrix, dtype=float).T.tolist()))

        def mesh(stage, path, vertices, counts, indices, color):
            obj = UsdGeom.Mesh.Define(stage, path)
            obj.CreatePointsAttr([Gf.Vec3f(*map(float, p)) for p in vertices])
            obj.CreateFaceVertexCountsAttr(counts)
            obj.CreateFaceVertexIndicesAttr(indices)
            obj.CreateSubdivisionSchemeAttr('none')
            obj.CreateDisplayColorAttr([Gf.Vec3f(*color)])
            obj.CreateDoubleSidedAttr(True)

        def sphere(stage, path, point, color, radius=.0035):
            obj = UsdGeom.Sphere.Define(stage, path)
            obj.CreateRadiusAttr(radius)
            obj.AddTranslateOp().Set(Gf.Vec3d(*map(float, point)))
            obj.CreateDisplayColorAttr([Gf.Vec3f(*color)])

        def curve(stage, path, points, color, width):
            obj = UsdGeom.BasisCurves.Define(stage, path)
            obj.CreateTypeAttr('linear'); obj.CreateWrapAttr('nonperiodic')
            obj.CreateCurveVertexCountsAttr([len(points)])
            obj.CreatePointsAttr([Gf.Vec3f(*map(float, p)) for p in points])
            obj.CreateWidthsAttr([width]); obj.CreateDisplayColorAttr([Gf.Vec3f(*color)])

        def capture(output, name):
            for _ in range(40):
                app.update()
            path = output / (name+'.png')
            viewport = get_active_viewport()
            viewport.set_texture_resolution((1280, 960))
            capture_viewport_to_file(viewport, str(path))
            deadline = time.monotonic()+20
            while time.monotonic() < deadline:
                app.update()
                if path.is_file() and path.stat().st_size > 1000:
                    return
            raise RuntimeError('Viewport capture incomplete')

        window = ui.Window('CURRENT VLA · UNVALIDATED PREVIEW', width=560, height=280)
        processed = set()
        log('READY '+session.name)
        event('READY', session_id=session.name)
        while app.is_running() and not (session/'stop.json').exists():
            app.update()
            pending = [p for p in sorted((session/'queue').glob('*.json')) if p.stem not in processed]
            if not pending:
                time.sleep(.02)
                continue
            request = pending[0]; processed.add(request.stem)
            result = session / 'results' / (request.stem+'.json')
            output = session / 'outputs' / request.stem
            output.mkdir(parents=True, exist_ok=False)
            phase = 'admission'
            dataset_v2 = False
            try:
                d, p, npz = resolve_command(read(request), read(session / 'catalog.json'))
                event('current_job_resolved', job_id=d['job_id'])
                event('current_vla_artifact_resolved', artifact_id=d['artifact_id'])
                event('exact_package_resolved', package_id=d['package_id'], npz_sha256=sha(npz))
                sim = Path(d['simulator_root'])
                sys.path.insert(0, str(sim))
                # Pure geometry/kinematics helpers; no external script main/registry.
                with np.load(npz, allow_pickle=False) as data:
                    predicted = data['predicted_path_m'].copy()
                    gt = data['ground_truth_path_m'].copy()
                if predicted.shape != (9, 3) or predicted.dtype != np.float32 or not np.isfinite(predicted).all():
                    raise ValueError('Invalid 9-point prediction')
                count = len(predicted)
                if count != d['point_count']:
                    raise ValueError('Prediction count differs from descriptor')
                event('prediction_checked', point_count=count, dtype='float32', finite=True)
                transform = np.asarray(d['source_to_scene'])
                world = predicted.astype(float) @ transform[:3, :3].T + transform[:3, 3]
                gt_world = gt.astype(float) @ transform[:3, :3].T + transform[:3, 3]
                dataset_v2 = d.get('backend') == 'dataset_v2'
                diagnostics = CaptureDiagnostics(output, event) if dataset_v2 else None

                def diagnostic_capture(name):
                    if diagnostics is None:
                        capture(output, name)
                        event('capture_written', file=name+'.png')
                        return
                    def request_capture(path):
                        viewport = get_active_viewport()
                        if viewport is None:
                            raise RuntimeError('Viewport unavailable')
                        viewport.set_texture_resolution((1280, 960))
                        capture_viewport_to_file(viewport, path)
                    diagnostics.attempt(name, request_capture=request_capture, update=app.update)

                native = None
                if dataset_v2:
                    with np.load(Path(d['package']).parent/'native/trajectory_solution.npz', allow_pickle=False) as data:
                        native = {key:data[key].copy() for key in data.files}
                omni.usd.get_context().new_stage()
                phase = 'stage_geometry'
                stage = omni.usd.get_context().get_stage()
                UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
                UsdGeom.SetStageMetersPerUnit(stage, 1.)
                stage.SetMetadata('customLayerData', {'mode':d['mode'], 'artifact_id':d['artifact_id'],
                    'sample':d['sample_id'], 'warning':'UNVALIDATED FIXTURE / SIMULATION PREVIEW ONLY / PHYSICAL EXECUTION DISABLED'})
                light = UsdLux.DomeLight.Define(stage, '/Light'); light.CreateIntensityAttr(1600.)
                work = np.empty((0,3))
                if d.get('show_workpiece', True):
                    if dataset_v2:
                        # Native scene builder output, including CAD rotation; no copied placement algorithm.
                        work = native['workpiece_vertices_world_m']
                        counts = native['workpiece_face_counts'].tolist()
                        indices = native['workpiece_face_indices'].tolist()
                    else:
                        from welding_workpiece import load_obj_mesh
                        verts, counts, indices = load_obj_mesh(Path(p['obj']))
                        work = verts*.001 + np.asarray(d['object_translation_m'])
                    mesh(stage, '/Workpiece', work, counts, indices, (.5, .56, .61))
                    event('workpiece_loaded', prim='/Workpiece', triangles=len(counts))
                else:
                    # Neutral source-frame axes only; no other sample's workpiece/table/robot.
                    for axis, color in enumerate(((1.,0.,0.),(0.,1.,0.),(0.,.3,1.))):
                        end = np.zeros(3); end[axis] = .1
                        curve(stage, '/SourceAxis'+str(axis), [np.zeros(3), end], color, .001)
                    event('source_frame_axes_created', units='meter', workpiece=False, robot=False)
                curve(stage, '/VLA_PREDICTED_9', world, (1., .22, .04), .003)
                event('prediction_path_created', prim='/VLA_PREDICTED_9', point_count=9)
                curve(stage, '/GT_REFERENCE_ONLY', gt_world, (.15, .8, .35), .0015)
                event('gt_reference_created', prim='/GT_REFERENCE_ONLY', gt_is_target=False)
                for i, point in enumerate(world):
                    sphere(stage, '/P'+str(i), point, (.05, .65, 1.) if i==0 else (1., .2, .04))
                for name, center, scale in (() if not len(work) else (
                    ('Ground', [0,0,-.025], [3,3,.05]),
                    ('DiagnosticTable', [float(work[:,0].mean()),float(work[:,1].mean()),float(work[:,2].min())-.02], [.3,.3,.04]))):
                    cube = UsdGeom.Cube.Define(stage, '/'+name); cube.CreateSizeAttr(1.)
                    cube.AddTranslateOp().Set(Gf.Vec3d(*center)); cube.AddScaleOp().Set(Gf.Vec3f(*scale))
                    cube.CreateDisplayColorAttr([Gf.Vec3f(.14,.18,.21)])
                with window.frame:
                    with ui.VStack(spacing=4):
                        ui.Label('UNVALIDATED FIXTURE · SIMULATION PREVIEW ONLY', style={'color':0xff55aaff})
                        ui.Label('PHYSICAL EXECUTION DISABLED · '+d['clearance_warning'])
                        ui.Label(d['sample_id']+' · '+str(count)+' points · '+d['kind'].upper()+' PREVIEW')
                        if dataset_v2:
                            ui.Label('Dataset Simulator v2 · 9 VLA source points / '+str(d['playback_point_count'])+' derived playback points')
                        ui.Label('Artifact '+d['artifact_id'])
                        ui.Label(d['coordinate_frame']+' · units=meter', word_wrap=True)
                        ui.Label(f"ADE {d['ade_mm']:.6f} mm / FDE {d['fde_mm']:.6f} mm")
                        ui.Label('orange: predicted XYZ / green: GT reference only')
                        ui.Label('orientation_source='+d['orientation_source']+'; vla_orientation=false')
                        waypoint_label = ui.Label('P0 → P'+str(count-1)+' · '+('native IK/FK' if d['kind']=='robot' else 'source-frame XYZ; robot motion disabled'))
                log(json.dumps({k:d[k] for k in ('sample_id','artifact_id','package_id','point_count','coordinate_frame','ade_mm','fde_mm','mode','clearance_warning')}))
                ops, joints, chain, poses = {}, None, None, None
                visual_evidence = []
                if d['kind'] == 'robot':
                    from welding_tool_geometry import mounted_cad_transform, mounted_tip_transform, CAD_TIP_LOCAL_MM
                    from prepare_rb5_h5_trajectory import UrdfChain, solve_path, JOINT_NAMES, matrix_from_xyz_rpy
                    phase = 'native_ik'
                    event('native_ik_started')
                    urdf = sim / 'rbpodo_description/robots/rb10_1300e_u.urdf'
                    tree = ET.parse(urdf).getroot()
                    chain = UrdfChain(urdf)
                    if dataset_v2:
                        # Already solved by run_welding_sample.prepare with its native full-pose policy.
                        poses = native['tcp_pose_xyz_mm_rpy_deg']
                        joints = native['joint_position_rad']
                        pos_errors = native['position_error_mm']
                        rot_errors = native['orientation_error_deg']
                    else:
                        euler = Rotation.from_matrix(np.asarray(d['flange_rotation'])).as_euler('xyz', degrees=True)
                        poses = np.column_stack((world*1000, np.tile(euler, (count, 1))))
                        joints, pos_errors, rot_errors = solve_path(chain, poses, mounted_tip_transform(), [0,-30,100,-60,-90,0])
                    # Native stage tip diagnostic uses 2 mm. This is not a clearance/safety gate.
                    if float(pos_errors.max()) > 2:
                        raise RuntimeError('Native diagnostic IK did not reach the unchanged prediction; use Path Preview')
                    event('native_ik_completed', point_count=len(poses), derived=dataset_v2, tip_error_mm_max=float(pos_errors.max()))
                    phase = 'robot_visuals'
                    for link in tree.findall('link'):
                        name = link.attrib['name']
                        ops[name] = matrix_op(stage, '/RB10/'+name)
                        for vi, visual in enumerate(link.findall('visual')):
                            asset = visual.find('geometry/mesh')
                            if asset is None:
                                continue
                            visual_path = (sim / asset.attrib['filename'].replace('package://','')).resolve()
                            if not visual_path.is_relative_to(sim):
                                raise ValueError('Robot mesh outside audited assets')
                            vertices, face_counts, face_indices = load_visual_mesh(visual_path)
                            vertices *= np.fromstring(asset.attrib.get('scale','1 1 1'), sep=' ')
                            origin = visual.find('origin')
                            if origin is not None:
                                local = matrix_from_xyz_rpy(np.fromstring(origin.attrib.get('xyz','0 0 0'),sep=' '),
                                    np.fromstring(origin.attrib.get('rpy','0 0 0'),sep=' '))
                                vertices = vertices @ local[:3,:3].T + local[:3,3]
                            visual_prim = '/RB10/'+name+'/Visual'+str(vi)
                            mesh(stage, visual_prim, vertices, face_counts,
                                 face_indices, (.42,.63,.78))
                            finite = bool(np.isfinite(vertices).all())
                            prim_created = bool(stage.GetPrimAtPath(visual_prim).IsValid())
                            if not finite or not prim_created:
                                raise ValueError('Invalid robot visual geometry')
                            visual_evidence.append(dict(file=visual_path.name, sha256=sha(visual_path),
                                vertices=len(vertices), triangles=len(face_counts), finite=finite,
                                dae_node_transform_applied=True, urdf_visual_transform_applied=True,
                                prim=visual_prim, prim_created=prim_created))
                            event('dae_visual_loaded', **visual_evidence[-1])
                    tool_op = matrix_op(stage, '/Tool')
                    geometry = UsdGeom.Xform.Define(stage, '/Tool/Geometry')
                    geometry.GetPrim().GetReferences().AddReference(str(sim/'ATU01035_welding_tool.usd'))
                    geometry.AddScaleOp().Set(Gf.Vec3f(.001,.001,.001))
                    event('tool_visual_loaded', prim='/Tool/Geometry', scale=.001)
                measured = []
                targets = poses[:,:3]*.001 if dataset_v2 and joints is not None else world
                parameters = native['playback_waypoint_parameter'] if dataset_v2 and joints is not None else np.arange(count)
                center = np.mean(work if len(work) else np.vstack((world,gt_world)), axis=0)
                set_camera_view(eye=(center+[-1.1,-1.3,.75]).tolist(), target=([.5,.12,.4] if len(work) else center.tolist()))
                def apply_waypoint(i):
                    nonlocal phase
                    phase = 'waypoint_P'+str(i)
                    waypoint_label.text = (f'Playback {i+1}/{len(targets)} · native interpolation · source parameter {parameters[i]:.3f}'
                        if dataset_v2 and joints is not None else f'P{i} / P{count-1} · target = predicted_path_m[{i}] · no GT control')
                    if joints is not None:
                        q = joints[i]; links = {'link0':np.eye(4)}
                        for j, name in enumerate((*JOINT_NAMES, 'tcp_joint')):
                            joint = next(v for v in tree.findall('joint') if v.attrib['name']==name)
                            origin = joint.find('origin')
                            local = matrix_from_xyz_rpy(np.fromstring(origin.attrib.get('xyz','0 0 0'),sep=' '),
                                np.fromstring(origin.attrib.get('rpy','0 0 0'),sep=' '))
                            rot = np.eye(4)
                            if joint.attrib['type'] != 'fixed':
                                rot[:3,:3] = Rotation.from_rotvec(np.fromstring(joint.find('axis').attrib['xyz'],sep=' ')*q[j]).as_matrix()
                            links[joint.find('child').attrib['link']] = links[joint.find('parent').attrib['link']] @ local @ rot
                        for name, op in ops.items():
                            set_matrix(op, links[name])
                        set_matrix(tool_op, links['tcp'] @ (native['cad_to_robot_tcp'] if dataset_v2 else mounted_cad_transform()))
                        cache = UsdGeom.XformCache(Usd.TimeCode.Default())
                        tip_local = native.get('weld_tip_local_mm', CAD_TIP_LOCAL_MM) if dataset_v2 else CAD_TIP_LOCAL_MM
                        actual = np.array(cache.GetLocalToWorldTransform(geometry.GetPrim()).Transform(Gf.Vec3d(*map(float,tip_local))))
                        measured.append(actual)
                        if np.linalg.norm(actual-targets[i])*1000 > (1 if dataset_v2 else 2):
                            raise RuntimeError('Actual stage tool tip does not match native FK target')
                    else:
                        measured.append(targets[i])
                    for _ in range(25):
                        app.update()
                    log(f'WAYPOINT P{i} predicted_path_m; physics=false')
                    event('waypoint_completed', waypoint=i, target_source='predicted_path_m',
                          tip_error_mm=float(np.linalg.norm(measured[-1]-targets[i])*1000),
                          link_fk_transforms_applied=joints is not None)

                def capture_waypoint(i):
                    nonlocal phase
                    source_index = next((k for k in (0,count//2,count-1) if abs(parameters[i]-k)<1e-12), None)
                    if source_index is not None:
                        phase = 'capture_P'+str(source_index)
                        diagnostic_capture('P'+str(source_index))

                play_waypoints(len(targets), apply_waypoint, capture_waypoint)
                event('final_pose_completed', waypoint=len(targets)-1)
                # Close-up is diagnostic evidence that all 9 points and the actual CAD are visible.
                set_camera_view(eye=(center+[-.6,-.55,.38]).tolist(), target=np.mean(np.vstack((world, work)),axis=0).tolist())
                phase = 'capture_detail'
                diagnostic_capture('path_detail')
                phase = 'export_evidence'
                if not stage.GetRootLayer().Export(str(output/'scene.usda')):
                    raise RuntimeError('Scene evidence export failed')
                np.savez(output/'waypoints.npz', predicted_path_m=predicted, ground_truth_path_m=gt,
                         source_to_scene=transform, predicted_world_m=world, measured_tip_world_m=np.asarray(measured),
                         playback_target_world_m=targets, playback_waypoint_parameter=parameters)
                with np.load(output/'waypoints.npz', allow_pickle=False) as recorded:
                    exact = np.array_equal(recorded['predicted_path_m'],predicted)
                report = dict(state='done',artifact_id=d['artifact_id'],package_id=d['package_id'],job_id=d['job_id'],
                    sample_id=d['sample_id'],point_count=count,trajectory_source='predicted_path_m',exact_xyz_preserved=exact,
                    npz_sha256=sha(npz),mode=d['mode'],kind=d['kind'],robot_motion=joints is not None,
                    physics_stepping=False,target_interpolation=dataset_v2 and joints is not None,gt_is_target=False,
                    fixture_ready=False,validated_simulation=False,physical_robot_executable=False,
                    orientation_source=d['orientation_source'],vla_orientation=False,
                    clearance_warning=d['clearance_warning'],ade_mm=d['ade_mm'],fde_mm=d['fde_mm'],
                    tip_error_mm_max=float(np.linalg.norm(np.asarray(measured)-targets,axis=1).max()*1000),
                    robot_visual_meshes=visual_evidence,
                    displayed_waypoints=list(range(count)),captures=['P0.png',f'P{count//2}.png',f'P{count-1}.png','path_detail.png'])
                if dataset_v2:
                    report.update(backend='dataset_v2', source_point_count=9, playback_point_count=d['playback_point_count'],
                        playback_derived=True, displayed_playback_points=len(targets), sample_family=d['family'],
                        playback_status='SUCCEEDED', completed_playback_points=len(measured), **diagnostics.summary())
                save(output/'report.json', report); save(result, report)
                event('result_written', state='done', exact_xyz_preserved=exact)
                log('DONE '+d['artifact_id']+' N=9 exact=true UNVALIDATED FIXTURE; PHYSICAL EXECUTION DISABLED')
            except Exception as exc:
                # Exception payloads may contain paths; report only the class.
                import traceback
                frames = [{'file':Path(f.filename).name,'line':f.lineno,'function':f.name}
                          for f in traceback.extract_tb(exc.__traceback__)]
                log('FAILED '+type(exc).__name__+' phase='+phase+'; no retry')
                failure = dict(state='failed',exception_class=type(exc).__name__,phase=phase,frames=frames)
                if dataset_v2:
                    failure.update(backend='dataset_v2', playback_status='FAILED', **diagnostics.summary())
                save(result, failure)
                event('failed', phase=phase, exception_class=type(exc).__name__)
    finally:
        app.close()
