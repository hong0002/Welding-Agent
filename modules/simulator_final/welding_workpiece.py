"""OBJ geometry helpers adapted from the existing validation viewer.

Placement is a visualization estimate, not calibrated camera/robot registration.
"""
import numpy as np

def rotation_between(source, target):
    source = np.array(source, dtype=np.float64, copy=True)
    target = np.array(target, dtype=np.float64, copy=True)
    source /= np.linalg.norm(source)
    target /= np.linalg.norm(target)
    cross = np.cross(source, target)
    dot = float(np.clip(np.dot(source, target), -1.0, 1.0))
    if np.linalg.norm(cross) < 1e-12:
        if dot > 0.0:
            return np.eye(3)
        helper = np.array([1.0, 0.0, 0.0])
        if abs(np.dot(source, helper)) > 0.9:
            helper = np.array([0.0, 1.0, 0.0])
        axis = np.cross(source, helper)
        axis /= np.linalg.norm(axis)
        return 2.0 * np.outer(axis, axis) - np.eye(3)
    skew = np.array([[0.0, -cross[2], cross[1]], [cross[2], 0.0, -cross[0]], [-cross[1], cross[0], 0.0]], dtype=np.float64)
    return np.eye(3) + skew + skew @ skew * ((1.0 - dot) / np.dot(cross, cross))

def load_obj_mesh(obj_path):
    vertices = []
    counts = []
    indices = []
    with open(obj_path, 'r', encoding='utf-8', errors='ignore') as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('v '):
                parts = line.split()
                if len(parts) >= 4:
                    vertices.append([float(parts[1]), float(parts[2]), float(parts[3])])
            elif line.startswith('f '):
                face = []
                for token in line.split()[1:]:
                    first = token.split('/')[0]
                    if not first:
                        continue
                    idx = int(first)
                    if idx > 0:
                        idx -= 1
                    else:
                        idx = len(vertices) + idx
                    face.append(idx)
                if len(face) >= 3:
                    counts.append(len(face))
                    indices.extend(face)
    vertices = np.asarray(vertices, dtype=np.float64)
    if len(vertices) == 0 or len(counts) == 0:
        raise RuntimeError(f'Could not read OBJ: {obj_path}')
    return (vertices, counts, indices)

def _obj_connected_components(vertex_count, counts, indices):
    """Return face-connected OBJ vertex components."""
    parent = np.arange(vertex_count, dtype=np.int64)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra = find(a)
        rb = find(b)
        if ra != rb:
            parent[rb] = ra
    cursor = 0
    for count in counts:
        face = indices[cursor:cursor + count]
        cursor += count
        if len(face) < 2:
            continue
        first = int(face[0])
        for idx in face[1:]:
            union(first, int(idx))
    groups = {}
    for index in range(vertex_count):
        root = find(index)
        groups.setdefault(root, []).append(index)
    components = [np.asarray(values, dtype=np.int64) for values in groups.values() if len(values) >= 8]
    components.sort(key=len, reverse=True)
    return components

def _pca_component(vertices_mm, component_indices):
    points = vertices_mm[component_indices]
    center = points.mean(axis=0)
    centered = points - center
    covariance = centered.T @ centered / max(len(points), 1)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    order = np.argsort(eigenvalues)[::-1]
    axes = eigenvectors[:, order]
    projected = centered @ axes
    extents = projected.max(axis=0) - projected.min(axis=0)
    return {'indices': component_indices, 'points': points, 'center': center, 'axes': axes, 'extents': extents}

def infer_plate_round_seam(vertices_mm, counts, indices):
    """Infer the physical Plate-Round seam from the OBJ geometry."""
    components = _obj_connected_components(len(vertices_mm), counts, indices)
    if len(components) < 2:
        raise RuntimeError(f'L_PR OBJ could not be separated into Plate + Round bodies. Detected {len(components)} connected component(s).')
    info = [_pca_component(vertices_mm, comp) for comp in components]
    print('\n[OBJ GEOMETRY]')
    for i, item in enumerate(info):
        print(f"  component {i}: vertices={len(item['indices'])}, PCA extents mm={item['extents'].tolist()}")
    plate_index = min(range(len(info)), key=lambda i: float(np.min(info[i]['extents'])) / max(float(np.max(info[i]['extents'])), 1e-9))
    plate = info[plate_index]
    plate_thickness_mm = float(np.min(plate['extents']))
    if plate_thickness_mm / max(float(np.max(plate['extents'])), 1e-9) > 0.25:
        raise RuntimeError(f'Could not identify a thin plate component. Best thickness={plate_thickness_mm:.3f} mm.')
    remaining = [(i, item) for i, item in enumerate(info) if i != plate_index]
    round_index, round_body = max(remaining, key=lambda pair: len(pair[1]['indices']))
    plate_small_axis = int(np.argmin(plate['extents']))
    plate_normal = np.array(plate['axes'][:, plate_small_axis], dtype=np.float64, copy=True)
    if np.dot(round_body['center'] - plate['center'], plate_normal) < 0.0:
        plate_normal *= -1.0
    plate_normal /= np.linalg.norm(plate_normal)
    round_major_axis = int(np.argmax(round_body['extents']))
    round_axis = np.array(round_body['axes'][:, round_major_axis], dtype=np.float64, copy=True)
    round_axis = round_axis - np.dot(round_axis, plate_normal) * plate_normal
    round_axis_norm = np.linalg.norm(round_axis)
    if round_axis_norm < 1e-08:
        raise RuntimeError('Round axis is parallel to plate normal; cannot infer Plate-Round seam.')
    round_axis /= round_axis_norm
    dominant = int(np.argmax(np.abs(round_axis)))
    if round_axis[dominant] < 0.0:
        round_axis *= -1.0
    side_axis = np.cross(round_axis, plate_normal)
    side_axis /= np.linalg.norm(side_axis)
    plate_projection = plate['points'] @ plate_normal
    plate_contact_plane = float(np.max(plate_projection))
    round_points = round_body['points']
    round_projection = round_points @ plate_normal
    contact_level = float(np.min(round_projection))
    contact_tolerance_mm = 1.5
    contact_mask = round_projection <= contact_level + contact_tolerance_mm
    contact_points = round_points[contact_mask]
    if len(contact_points) < 4:
        contact_tolerance_mm = 3.0
        contact_mask = round_projection <= contact_level + contact_tolerance_mm
        contact_points = round_points[contact_mask]
    if len(contact_points) < 2:
        raise RuntimeError('Could not detect the Plate-Round contact seam from OBJ vertices.')
    contact_center = np.mean(contact_points, axis=0)
    current_level = float(np.dot(contact_center, plate_normal))
    seam_center_mm = contact_center + (plate_contact_plane - current_level) * plate_normal
    round_axis_coord = round_points @ round_axis
    seam_axis_min_mm = float(np.min(round_axis_coord))
    seam_axis_max_mm = float(np.max(round_axis_coord))
    seam_length_mm = seam_axis_max_mm - seam_axis_min_mm
    local_basis = np.column_stack((side_axis, round_axis, plate_normal))
    print(f'[OBJ GEOMETRY] plate component={plate_index}, thickness≈{plate_thickness_mm:.3f} mm')
    print(f'[OBJ GEOMETRY] round component={round_index}, axis={round_axis.tolist()}')
    print(f'[OBJ GEOMETRY] plate->round normal={plate_normal.tolist()}')
    print(f'[OBJ GEOMETRY] seam centre mm={seam_center_mm.tolist()}')
    print(f'[OBJ GEOMETRY] seam length≈{seam_length_mm:.3f} mm')
    return {'plate': plate, 'round': round_body, 'local_basis': local_basis, 'side_axis': side_axis, 'seam_axis': round_axis, 'plate_normal': plate_normal, 'seam_center_mm': seam_center_mm, 'seam_length_mm': seam_length_mm}


def prepare_workpiece(obj_path, sample_id, trajectory_m, rpy_deg=None, label_path=None):
    vertices, counts, indices = load_obj_mesh(obj_path)
    if not np.isfinite(vertices).all() or min(indices) < 0 or max(indices) >= len(vertices):
        raise ValueError(f'Invalid OBJ geometry: {obj_path}')
    rotation = np.eye(3)
    target_center = np.mean(trajectory_m, axis=0)
    method = 'preview_bbox_top_center; NOT seam registered'
    # Generic fallback: preserve CAD axes and place its top-centre at the path.
    # Do not use the Plate-Round heuristic for unrelated joint types.
    anchor_mm = (vertices.min(axis=0) + vertices.max(axis=0)) / 2
    anchor_mm[2] = vertices[:, 2].max()
    if sample_id.startswith('L_PR_'):
        geometry = infer_plate_round_seam(vertices, counts, indices)
        direction = trajectory_m[-1] - trajectory_m[0]
        if np.linalg.norm(direction) < 1e-8:
            raise ValueError('Cannot align OBJ to a zero-length path')
        rotation = rotation_between(geometry['seam_axis'], direction)
        anchor_mm = geometry['seam_center_mm']
        method = 'estimated_plate_round_seam; roll uses minimum rotation, NOT calibrated'
        if rpy_deg is not None:
            from scipy.spatial.transform import Rotation
            # CAD's provisional approach is local -Y, so +Y points towards the torch.
            # Use it only to resolve the seam-axis roll; this is an explicit prior.
            seam = direction / np.linalg.norm(direction)
            outward = Rotation.from_euler('xyz', rpy_deg, degrees=True).as_matrix()[:, :, 1].mean(axis=0)
            outward -= seam * np.dot(outward, seam)
            if np.linalg.norm(outward) < 1e-5:
                raise ValueError('TCP approach parallel to seam; cannot estimate workpiece roll')
            outward /= np.linalg.norm(outward)
            side = np.cross(seam, outward)
            basis = np.column_stack((side, seam, outward))
            rotation = basis @ geometry['local_basis'].T
            method = 'pose_guided_seam; TCP +Y outward prior, NOT calibrated object pose'
    translation = target_center - rotation @ (anchor_mm * .001)
    world = (rotation @ (vertices * .001).T).T + translation
    report = dict(source_obj=str(obj_path), placement=method,
                  dimensions_mm=np.ptp(vertices, axis=0).tolist(),
                  obj_to_world_rotation=rotation.tolist(),
                  obj_to_world_translation_m=translation.tolist())
    if label_path is not None:
        raw = np.loadtxt(label_path, delimiter=',', usecols=(0, 1, 2, 6))
        seam_points = raw[raw[:, 3] == 0, :3]
        if len(seam_points) < 3:
            raise ValueError(f'Too few label-0 weld points in {label_path}')
        center = seam_points.mean(axis=0)
        _, _, vh = np.linalg.svd(seam_points - center, full_matrices=False)
        axial = (seam_points - center) @ vh[0]
        radial = seam_points - center - axial[:, None] * vh[0]
        report['measured_label_check'] = dict(
            source_csv=str(label_path), weld_label=0, point_count=len(seam_points),
            measured_seam_length_mm=float(np.ptp(axial) * 1000),
            measured_seam_rms_width_mm=float(np.sqrt(np.mean(np.sum(radial**2, axis=1))) * 1000),
            h5_endpoint_distance_mm=float(np.linalg.norm(trajectory_m[-1]-trajectory_m[0])*1000),
            note='Shape/length comparison only; no measured-to-robot extrinsic supplied.')
        print('[MEASURED SEAM]', report['measured_label_check'], flush=True)
    print(f'[WORKPIECE] {sample_id}: {len(vertices)} vertices, {len(counts)} faces; {method}', flush=True)
    return dict(workpiece_vertices_world_m=world,
                workpiece_face_counts=np.asarray(counts, dtype=np.int32),
                workpiece_face_indices=np.asarray(indices, dtype=np.int32)), report


def add_workpiece(stage, solution):
    from pxr import Gf, UsdGeom
    if 'workpiece_vertices_world_m' not in solution:
        print('[WORKPIECE] No mesh in legacy solution; send the sample again to include its OBJ.', flush=True)
        return
    vertices = np.asarray(solution['workpiece_vertices_world_m'])
    mesh = UsdGeom.Mesh.Define(stage, '/WeldingWorkpiece')
    mesh.CreatePointsAttr([Gf.Vec3f(*map(float, v)) for v in vertices])
    mesh.CreateFaceVertexCountsAttr(solution['workpiece_face_counts'].tolist())
    mesh.CreateFaceVertexIndicesAttr(solution['workpiece_face_indices'].tolist())
    mesh.CreateSubdivisionSchemeAttr('none')
    mesh.CreateDoubleSidedAttr(True)
    mesh.CreateDisplayColorAttr([Gf.Vec3f(.48, .55, .62)])
    mesh.CreateExtentAttr([Gf.Vec3f(*map(float, vertices.min(axis=0))),
                           Gf.Vec3f(*map(float, vertices.max(axis=0)))])
    print(f'[WORKPIECE] Mesh displayed: {len(vertices)} vertices', flush=True)
