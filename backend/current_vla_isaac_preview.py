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
            try:
                d, p, npz = resolve_command(read(request), read(session / 'catalog.json'))
                event('current_job_resolved', job_id=d['job_id'])
                event('current_vla_artifact_resolved', artifact_id=d['artifact_id'])
                event('exact_package_resolved', package_id=d['package_id'], npz_sha256=sha(npz))
                sim = Path(d['simulator_root'])
                sys.path.insert(0, str(sim))
                # Pure geometry/kinematics helpers; no external script main/registry.
                from welding_workpiece import load_obj_mesh
                from welding_tool_geometry import mounted_cad_transform, mounted_tip_transform, CAD_TIP_LOCAL_MM
                from prepare_rb5_h5_trajectory import UrdfChain, solve_path, JOINT_NAMES, matrix_from_xyz_rpy
                with np.load(npz, allow_pickle=False) as data:
                    predicted = data['predicted_path_m'].copy()
                    gt = data['ground_truth_path_m'].copy()
                if predicted.shape != (9, 3) or predicted.dtype != np.float32 or not np.isfinite(predicted).all():
                    raise ValueError('Invalid 9-point prediction')
                event('prediction_checked', point_count=9, dtype='float32', finite=True)
                transform = np.asarray(d['source_to_scene'])
                world = predicted.astype(float) @ transform[:3, :3].T + transform[:3, 3]
                gt_world = gt.astype(float) @ transform[:3, :3].T + transform[:3, 3]
                omni.usd.get_context().new_stage()
                phase = 'stage_geometry'
                stage = omni.usd.get_context().get_stage()
                UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
                UsdGeom.SetStageMetersPerUnit(stage, 1.)
                stage.SetMetadata('customLayerData', {'mode':d['mode'], 'artifact_id':d['artifact_id'],
                    'sample':d['sample_id'], 'warning':'UNVALIDATED FIXTURE / SIMULATION PREVIEW ONLY / PHYSICAL EXECUTION DISABLED'})
                light = UsdLux.DomeLight.Define(stage, '/Light'); light.CreateIntensityAttr(1600.)
                verts, counts, indices = load_obj_mesh(Path(p['obj']))
                work = verts*.001 + np.asarray(d['object_translation_m'])
                mesh(stage, '/Workpiece', work, counts, indices, (.5, .56, .61))
                event('workpiece_loaded', prim='/Workpiece', triangles=len(counts))
                curve(stage, '/VLA_PREDICTED_9', world, (1., .22, .04), .003)
                event('prediction_path_created', prim='/VLA_PREDICTED_9', point_count=9)
                curve(stage, '/GT_REFERENCE_ONLY', gt_world, (.15, .8, .35), .0015)
                event('gt_reference_created', prim='/GT_REFERENCE_ONLY', gt_is_target=False)
                for i, point in enumerate(world):
                    sphere(stage, '/P'+str(i), point, (.05, .65, 1.) if i==0 else (1., .2, .04))
                for name, center, scale in (
                    ('Ground', [0,0,-.025], [3,3,.05]),
                    ('DiagnosticTable', [float(work[:,0].mean()),float(work[:,1].mean()),float(work[:,2].min())-.02], [.3,.3,.04])):
                    cube = UsdGeom.Cube.Define(stage, '/'+name); cube.CreateSizeAttr(1.)
                    cube.AddTranslateOp().Set(Gf.Vec3d(*center)); cube.AddScaleOp().Set(Gf.Vec3f(*scale))
                    cube.CreateDisplayColorAttr([Gf.Vec3f(.14,.18,.21)])
                with window.frame:
                    with ui.VStack(spacing=4):
                        ui.Label('UNVALIDATED FIXTURE · SIMULATION PREVIEW ONLY', style={'color':0xff55aaff})
                        ui.Label('PHYSICAL EXECUTION DISABLED · B_PR_TOOL_CLEARANCE_FAIL')
                        ui.Label(d['sample_id']+' · 9 points · '+d['kind'].upper()+' PREVIEW')
                        ui.Label('Artifact '+d['artifact_id'])
                        ui.Label(d['coordinate_frame'], word_wrap=True)
                        ui.Label(f"ADE {d['ade_mm']:.6f} mm / FDE {d['fde_mm']:.6f} mm")
                        ui.Label('orange: predicted XYZ / green: GT reference only')
                        ui.Label('orientation_source=simulator_fixture_policy; vla_orientation=false')
                        waypoint_label = ui.Label('P0 → P8 · discrete native IK/FK · physics disabled')
                log(json.dumps({k:d[k] for k in ('sample_id','artifact_id','package_id','point_count','coordinate_frame','ade_mm','fde_mm','mode','clearance_warning')}))
                ops, joints, chain, poses = {}, None, None, None
                visual_evidence = []
                if d['kind'] == 'robot':
                    phase = 'native_ik'
                    event('native_ik_started')
                    urdf = sim / 'rbpodo_description/robots/rb10_1300e_u.urdf'
                    tree = ET.parse(urdf).getroot()
                    chain = UrdfChain(urdf)
                    euler = Rotation.from_matrix(np.asarray(d['flange_rotation'])).as_euler('xyz', degrees=True)
                    poses = np.column_stack((world*1000, np.tile(euler, (9, 1))))
                    joints, pos_errors, rot_errors = solve_path(chain, poses, mounted_tip_transform(), [0,-30,100,-60,-90,0])
                    # Native stage tip diagnostic uses 2 mm. This is not a clearance/safety gate.
                    if float(pos_errors.max()) > 2:
                        raise RuntimeError('Native diagnostic IK did not reach the unchanged prediction; use Path Preview')
                    event('native_ik_completed', point_count=9, tip_error_mm_max=float(pos_errors.max()))
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
                center = np.mean(work, axis=0)
                set_camera_view(eye=(center+[-1.1,-1.3,.75]).tolist(), target=[.5,.12,.4])
                for i in range(9):
                    phase = 'waypoint_P'+str(i)
                    waypoint_label.text = f'P{i} / P8 · target = predicted_path_m[{i}] · no GT control'
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
                        set_matrix(tool_op, links['tcp'] @ mounted_cad_transform())
                        cache = UsdGeom.XformCache(Usd.TimeCode.Default())
                        actual = np.array(cache.GetLocalToWorldTransform(geometry.GetPrim()).Transform(Gf.Vec3d(*map(float,CAD_TIP_LOCAL_MM))))
                        measured.append(actual)
                        if np.linalg.norm(actual-world[i])*1000 > 2:
                            raise RuntimeError('Actual stage tool tip does not match native FK target')
                    else:
                        measured.append(world[i])
                    for _ in range(25):
                        app.update()
                    log(f'WAYPOINT P{i} predicted_path_m; physics=false')
                    event('waypoint_completed', waypoint=i, target_source='predicted_path_m',
                          tip_error_mm=float(np.linalg.norm(measured[-1]-world[i])*1000),
                          link_fk_transforms_applied=joints is not None)
                    if i in (0,4,8):
                        phase = 'capture_P'+str(i)
                        capture(output, 'P'+str(i))
                        event('capture_written', file='P'+str(i)+'.png')
                event('final_pose_completed', waypoint=8)
                # Close-up is diagnostic evidence that all 9 points and the actual CAD are visible.
                set_camera_view(eye=(center+[-.6,-.55,.38]).tolist(), target=np.mean(np.vstack((world, work)),axis=0).tolist())
                phase = 'capture_detail'
                capture(output, 'path_detail')
                event('capture_written', file='path_detail.png')
                phase = 'export_evidence'
                stage.GetRootLayer().Export(str(output/'scene.usda'))
                np.savez(output/'waypoints.npz', predicted_path_m=predicted, ground_truth_path_m=gt,
                         source_to_scene=transform, predicted_world_m=world, measured_tip_world_m=np.asarray(measured))
                with np.load(output/'waypoints.npz', allow_pickle=False) as recorded:
                    exact = np.array_equal(recorded['predicted_path_m'],predicted)
                report = dict(state='done',artifact_id=d['artifact_id'],package_id=d['package_id'],job_id=d['job_id'],
                    sample_id=d['sample_id'],point_count=9,trajectory_source='predicted_path_m',exact_xyz_preserved=exact,
                    npz_sha256=sha(npz),mode=d['mode'],kind=d['kind'],robot_motion=joints is not None,
                    physics_stepping=False,target_interpolation=False,gt_is_target=False,
                    fixture_ready=False,validated_simulation=False,physical_robot_executable=False,
                    orientation_source='simulator_fixture_policy',vla_orientation=False,
                    clearance_warning='B_PR_TOOL_CLEARANCE_FAIL',ade_mm=d['ade_mm'],fde_mm=d['fde_mm'],
                    tip_error_mm_max=float(np.linalg.norm(np.asarray(measured)-world,axis=1).max()*1000),
                    robot_visual_meshes=visual_evidence,
                    displayed_waypoints=list(range(9)),captures=['P0.png','P4.png','P8.png','path_detail.png'])
                save(output/'report.json', report); save(result, report)
                event('result_written', state='done', exact_xyz_preserved=exact)
                log('DONE '+d['artifact_id']+' N=9 exact=true UNVALIDATED FIXTURE; PHYSICAL EXECUTION DISABLED')
            except Exception as exc:
                # Exception payloads may contain paths; report only the class.
                import traceback
                frames = [{'file':Path(f.filename).name,'line':f.lineno,'function':f.name}
                          for f in traceback.extract_tb(exc.__traceback__)]
                log('FAILED '+type(exc).__name__+' phase='+phase+'; no retry')
                save(result, dict(state='failed',exception_class=type(exc).__name__,phase=phase,frames=frames))
                event('failed', phase=phase, exception_class=type(exc).__name__)
    finally:
        app.close()
