"""CAD-contact based preview placement for all five joints and six material pairs.

The contact candidates come from the two OBJ bodies, not a fabricated weld line.
Rigid registration uses GT XYZ only; it is a simulation placement, not a recovered
camera/robot calibration. No scaling, projection or modification of the raw path.
Requires trimesh and rtree in addition to numpy/scipy.
"""
from functools import lru_cache
from itertools import permutations, product

import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

from welding_workpiece import _obj_connected_components


def triangles_from_faces(counts, indices):
    triangles = []
    offset = 0
    for count in counts:
        face = indices[offset:offset + count]
        offset += count
        triangles.extend((face[0], face[j], face[j + 1]) for j in range(1, count - 1))
    return np.asarray(triangles, dtype=np.int64)


@lru_cache(maxsize=256)
def _contact_geometry(vertex_bytes, counts, indices):
    # Cache by actual geometry, not sample name: many episodes share a CAD model.
    import trimesh

    vertices = np.frombuffer(vertex_bytes, dtype=np.float64).reshape(-1, 3)
    faces = triangles_from_faces(counts, indices)
    components = _obj_connected_components(len(vertices), counts, indices)
    if len(components) != 2:
        raise ValueError(f'CAD contact extraction requires two bodies; found {len(components)}')
    meshes = []
    for component in components:
        mesh = trimesh.Trimesh(vertices, faces[np.isin(faces[:, 0], component)], process=False)
        mesh.remove_unreferenced_vertices()
        meshes.append(mesh)
    samples, nearest, distances, intersections = [], [], [], []
    for first, second in (meshes, meshes[::-1]):
        # Exclude coplanar face triangulation diagonals. Keep curved and sharp edges.
        edges = first.face_adjacency_edges[first.face_adjacency_angles > 1e-4]
        edge_count = np.bincount(first.edges_unique_inverse, minlength=len(first.edges_unique))
        edges = np.concatenate((edges, first.edges_unique[edge_count == 1]))
        segments = first.vertices[edges]
        points = np.concatenate([np.linspace(a, b, max(2, int(np.ceil(np.linalg.norm(b-a)/2)) + 1))
                                 for a, b in segments])
        # AABB lower bounds prune most of the long axial edges of cylinders.
        # Re-expand using the measured best distance, so gap contacts are retained.
        low, high = second.bounds
        lower_bound = np.linalg.norm(np.maximum(np.maximum(low-points, points-high), 0), axis=1)
        initial = lower_bound <= lower_bound.min() + .35
        near, distance, _ = trimesh.proximity.closest_point(second, points[initial])
        extra = ~initial & (lower_bound <= float(distance.min()) + .35)
        selected = points[initial]
        if extra.any():
            extra_near, extra_distance, _ = trimesh.proximity.closest_point(second, points[extra])
            selected = np.vstack((selected, points[extra]))
            near = np.vstack((near, extra_near))
            distance = np.r_[distance, extra_distance]
        samples.append(selected); nearest.append(near); distances.append(distance)
        if distance.min() > .35:
            # Crossing surfaces can have no nearby sampled vertices. Include cuts.
            vectors = segments[:, 1] - segments[:, 0]
            lengths = np.linalg.norm(vectors, axis=1)
            valid = (lengths > 1e-9) & np.all(segments.max(1) >= low, axis=1) & np.all(segments.min(1) <= high, axis=1)
            segments, vectors, lengths = segments[valid], vectors[valid], lengths[valid]
            if len(segments):
                directions = vectors / lengths[:, None]
                locations, rays, _ = second.ray.intersects_location(
                    segments[:, 0] - directions * .001, directions, multiple_hits=True)
                locations = np.asarray(locations).reshape(-1, 3)
                rays = np.asarray(rays, dtype=np.int64)
                along = np.einsum('ij,ij->i', locations - segments[rays, 0], directions[rays])
                intersections.extend(locations[(along >= -.002) & (along <= lengths[rays] + .002)])
    samples, nearest, distances = map(np.concatenate, (samples, nearest, distances))
    gap = 0. if intersections else float(distances.min())
    # CADs include intentional clearances (e.g. T_RR ~1 mm, C_RS ~5 mm).
    # Keep the gap visible and report it; never move the two bodies independently.
    mask = distances <= gap + .35
    contact = (samples[mask] + nearest[mask]) / 2
    if intersections:
        contact = np.vstack((contact, intersections))
    contact = np.unique(np.round(contact, 4), axis=0)
    if len(contact) < 3 or np.linalg.norm(np.ptp(contact, axis=0)) < 1e-6:
        raise ValueError('Cannot resolve a contact curve from this CAD')
    return contact, gap, meshes


def contact_geometry(vertices, counts, indices):
    return _contact_geometry(np.asarray(vertices, dtype=np.float64).tobytes(),
                             tuple(counts), tuple(indices))


def principal_basis(points):
    from contact_registration_determinism import canonical_principal_basis
    return canonical_principal_basis(points)


def rigid_fit(source, target):
    from contact_registration_determinism import deterministic_rigid_fit
    return deterministic_rigid_fit(source, target)


def register_path(source, contact):
    """Multi-start rigid ICP. Residual is retained, including length/shape mismatch."""
    if not np.isfinite(source).all() or np.linalg.norm(np.ptp(source, axis=0)) < 1e-6:
        raise ValueError('Source XYZ is non-finite or has zero spatial extent')
    points = source[np.unique(np.linspace(0, len(source)-1, min(64, len(source))).astype(int))]
    source_basis, target_basis = principal_basis(points), principal_basis(contact)
    tree = cKDTree(contact)
    from contact_registration_determinism import deterministic_nearest
    # Include the middle and extremal contacts so short arcs can fit a long seam.
    coordinates = (contact-contact.mean(0)) @ target_basis
    anchors = [contact.mean(0)]
    anchors.extend(contact[int(np.argmin(coordinates[:, a]))] for a in range(3))
    anchors.extend(contact[int(np.argmax(coordinates[:, a]))] for a in range(3))
    anchors = np.unique(np.round(anchors, 5), axis=0)
    best = None
    for order in permutations(range(3)):
        for signs in product((-1, 1), repeat=3):
            candidate = target_basis[:, order] @ np.diag(signs) @ source_basis.T
            if np.linalg.det(candidate) < 0:
                continue
            for anchor in anchors:
                rotation = candidate.copy()
                translation = anchor - rotation @ points.mean(0)
                previous = np.inf
                for _ in range(24):
                    transformed = points @ rotation.T + translation
                    distance, indices = deterministic_nearest(tree, transformed)
                    error = float(np.mean(distance**2))
                    if previous-error < 1e-7:
                        break
                    previous = error
                    from contact_registration_determinism import registration_update
                    rotation, translation = registration_update(points, contact[indices], rotation, translation)
                distance, _ = deterministic_nearest(tree, points @ rotation.T + translation)
                error = float(np.mean(distance**2))
                # Tie-break geometrically equivalent fits in favour of high/front seams.
                center = points.mean(0) @ rotation.T + translation
                preference = float(np.dot(center-contact.mean(0), [0, -1, 1]))
                score = error - 1e-5 * preference
                from contact_registration_determinism import registration_preference, prefer_registration
                preference_key = registration_preference(points, rotation, translation)
                if prefer_registration(score, preference_key, best):
                    best = score, rotation, translation, preference_key
    rotation, translation = best[1:3]
    fitted = source @ rotation.T + translation
    distance, indices = deterministic_nearest(tree, fitted)
    return fitted, rotation, translation, distance, indices


def accessible_direction(contact, meshes):
    """Choose an unobstructed approach on CAD contact points, not predicted XYZ."""
    points = contact[np.unique(np.linspace(0, len(contact)-1, min(12, len(contact))).astype(int))]
    best = None
    for raw in product((-1., 0., 1.), repeat=3):
        direction = np.asarray(raw)
        if not direction.any() or direction[2] < 0:
            continue
        direction /= np.linalg.norm(direction)
        origins = points + direction * 1.0
        blocked = np.zeros(len(points), dtype=bool)
        for mesh in meshes:
            blocked |= mesh.ray.intersects_any(origins, np.tile(direction, (len(points), 1)))
        # Prefer above/front when several directions are unobstructed.
        score = float(blocked.mean()) + .015*(1-direction[2]) + .005*direction[1]
        if best is None or score < best[0]:
            best = score, direction, float(blocked.mean())
    return best[1], best[2]


def upright_round_butt(contact, meshes, sample):
    """Recognize a coaxial tube butt joint; use the standing B_RR fixture convention.

    This is a fixture policy, not camera extrinsic calibration. Other families
    retain their CAD up. Return an ordered *CAD* outer rim, never replacement GT.
    """
    identity = np.eye(3)
    if not sample.startswith('B_RR_'):
        return identity, None
    center = contact.mean(0)
    basis = principal_basis(contact)
    normal = basis[:, 2].copy()
    if normal[np.argmax(np.abs(normal))] < 0:
        normal *= -1
    local = (contact-center) @ basis
    if np.max(np.abs(local[:, 2])) > .5:
        return identity, None
    # Fit the center, then retain the actual outer contact-edge samples. Tubes
    # have both inner and outer rims; joining all contact points makes a zigzag.
    xy = local[:, :2]
    fit = np.linalg.lstsq(np.c_[2*xy, np.ones(len(xy))], (xy*xy).sum(1), rcond=None)[0]
    center += basis[:, :2] @ fit[:2]
    xy -= fit[:2]
    radii = np.linalg.norm(xy, axis=1)
    radius = radii.max()
    if radius < 1 or np.ptp(radii) > .35*radius:
        return identity, None
    for mesh in meshes:
        axis = principal_basis(mesh.vertices)[:, 0]
        offset = mesh.vertices.mean(0)-center
        if abs(axis @ normal) < .995 or np.linalg.norm(offset-normal*(offset@normal)) > max(.5, .02*radius):
            return identity, None
    outer = radii >= radius-.15
    angles = np.arctan2(xy[outer, 1], xy[outer, 0])
    if outer.sum() < 12 or np.diff(np.r_[np.sort(angles), angles.min()+2*np.pi]).max() > np.pi/6:
        return identity, None
    rim = contact[outer][np.argsort(angles)]
    rim = np.vstack((rim, rim[0]))
    cross = np.cross(normal, [0., 0., 1.])
    angle = np.arccos(np.clip(normal[2], -1., 1.))
    if np.linalg.norm(cross) < 1e-10:
        rotation = identity if normal[2] > 0 else Rotation.from_euler('x', np.pi).as_matrix()
    else:
        rotation = Rotation.from_rotvec(cross/np.linalg.norm(cross)*angle).as_matrix()
    return rotation, rim


def build_contact_scene(vertices, counts, indices, sample, source_poses):
    contact, gap, meshes = contact_geometry(vertices, counts, indices)
    outer_contact_count = None
    if sample.startswith('T_RR_'):
        from welding_round_orientation import fit_tubes
        tubes = fit_tubes(dict(workpiece_vertices_world_m=vertices*.001,
                               workpiece_face_counts=counts, workpiece_face_indices=indices))
        exterior = np.ones(len(contact), dtype=bool)
        for center, axis, _, radius in tubes:
            delta = contact-center
            radial = np.linalg.norm(delta-(delta@axis)[:,None]*axis, axis=1)
            exterior &= radial >= radius-.6
        if exterior.sum() < 3:
            raise ValueError('T_RR exterior contact curve could not be resolved')
        contact = contact[exterior]
        outer_contact_count = len(contact)
    upright, cad_rim = upright_round_butt(contact, meshes, sample)
    # Perform registration and approach selection in the upright fixture frame,
    # so their front/up preferences use the same axes as the rendered workpiece.
    if not np.allclose(upright, np.eye(3)):
        contact = contact @ upright.T
        transform = np.eye(4); transform[:3, :3] = upright
        meshes = [mesh.copy() for mesh in meshes]
        for mesh in meshes:
            mesh.apply_transform(transform)
    fitted, path_rotation, path_translation, distance, nearest = register_path(source_poses[:, :3], contact)
    outward, blocked_fraction = accessible_direction(contact[nearest], meshes)
    if sample.startswith('T_RR_'):
        # Face the actual seam towards the robot instead of selecting the open
        # tube bore's unobstructed vertical ray as the global approach direction.
        normals = []
        for center, axis, _, _ in tubes:
            delta = fitted-center
            radial = delta-(delta@axis)[:,None]*axis
            normals.append(radial/np.maximum(np.linalg.norm(radial,axis=1)[:,None],1e-9))
        direction = (normals[0]+normals[1]).mean(0)
        if np.linalg.norm(direction[:2]) < 1e-6:
            direction = normals[0][0]+normals[1][0]
        outward = direction/np.linalg.norm(direction)
        blocked_fraction = None  # This direction selects fixture yaw, not a ray-clearance result.
    # Preserve the chosen fixture up (CAD up except recognized standing B_RR).
    # Only yaw towards the robot; generic seam alignment would tilt flat plates.
    horizontal = np.linalg.norm(outward[:2])
    yaw = np.pi - np.arctan2(outward[1], outward[0]) if horizontal > 1e-8 else 0.
    fixture_rotation = Rotation.from_euler('z', yaw).as_matrix()
    object_rotation = fixture_rotation @ upright
    world_outward = fixture_rotation @ outward
    fixture_center = np.array([.85, .15, .50])
    if world_outward[2] > .95 and np.ptp(fitted[:, 2]) > 150.:
        # Leave reach for the 43 cm torch on tall vertical source paths.
        fixture_center = np.array([.75, .15, .45])
    object_translation = fixture_center - fixture_rotation @ fitted.mean(0)*.001
    rotation = fixture_rotation @ path_rotation
    translation = fixture_rotation @ path_translation*.001 + object_translation
    poses = source_poses.copy()
    poses[:, :3] = ((source_poses[:, :3]*.001) @ rotation.T + translation)*1000
    # XYZ demonstration: use one explicitly synthetic orientation for new families.
    poses[:, 3:] = Rotation.from_matrix(rotation).as_euler('xyz', degrees=True)
    world = (vertices*.001) @ object_rotation.T + object_translation
    rigid = np.eye(4); rigid[:3, :3] = rotation; rigid[:3, 3] = translation
    arrays = dict(workpiece_vertices_world_m=world,
                  workpiece_face_counts=np.asarray(counts, dtype=np.int32),
                  workpiece_face_indices=np.asarray(indices, dtype=np.int32),
                  source_to_scene=rigid, source_tcp_pose_xyz_mm_rpy_deg=source_poses,
                  fixture_table_top_m=np.asarray(world[:, 2].min()),
                  fixture_outward=world_outward, fixture_fixed_orientation=np.asarray(True),
                  camera_eye_offset_m=np.array([-.8, -1.3, .85]))
    report = dict(placement=('exterior T_RR contact + rigid GT XYZ registration; per-point torch preview'
                            if sample.startswith('T_RR_') else 'CAD contact candidates + rigid GT XYZ registration; fixed torch preview'),
                  family='_'.join(sample.split('_')[:2]), original_cad_axes_preserved=bool(np.allclose(object_rotation, np.eye(3))),
                  original_cad_up_preserved=bool(np.allclose(object_rotation @ [0, 0, 1], [0, 0, 1])),
                  object_orientation_policy=('coaxial B_RR standing fixture; circular contact normal aligned to world Z'
                                             if cad_rim is not None else 'preserve CAD Z up; yaw only'),
                  object_deformed=False, obj_to_world_rotation=object_rotation.tolist(),
                  obj_to_world_translation_m=object_translation.tolist(), source_to_scene=rigid.tolist(),
                  contact_candidate_count=len(contact), cad_contact_gap_mm=gap,
                  exterior_round_contact_count=outer_contact_count,
                  gt_to_contact_mm_mean=float(distance.mean()), gt_to_contact_mm_max=float(distance.max()),
                  approach_ray_blocked_fraction=blocked_fraction,
                  orientation_policy='fixed fixture orientation; original H5 orientation not replayed',
                  note='Estimated simulation placement, not calibrated registration or collision certification. '
                       'CAD bodies and source path are not scaled/deformed. Residuals include sampling and shape mismatch.')
    if cad_rim is not None:
        arrays['cad_contact_curve_world_m'] = (cad_rim*.001) @ object_rotation.T + object_translation
        path_length = float(np.linalg.norm(np.diff(source_poses[:, :3], axis=0), axis=1).sum())
        rim_length = float(np.linalg.norm(np.diff(cad_rim, axis=0), axis=1).sum())
        report.update(source_path_length_mm=path_length, cad_outer_rim_length_mm=rim_length,
                      cad_contact_curve_role='CAD joint outline only; not GT, prediction or robot target',
                      source_path_to_full_rim_length_ratio=path_length/rim_length)
        print(f'[CAD RIM] {sample}: upright; source path={path_length:.2f} mm; '
              f'full CAD rim={rim_length:.2f} mm; cyan=CAD reference only', flush=True)
        if path_length < .25*rim_length:
            report['short_source_path_notice'] = 'Source covers much less length than the CAD circumference; partial path or source/CAD mismatch. No automatic rescaling.'
            print('[SOURCE PATH] Short H5 path preserved. CAD circumference is not substituted for GT.', flush=True)
    print(f'[FIXTURE] {sample}: CAD contact preview; gap={gap:.2f} mm; '
          f'GT/contact mean={distance.mean():.2f}, max={distance.max():.2f} mm', flush=True)
    return poses, arrays, report
