"""Resolve PCA signs and equivalent contact registrations in native CAD axes.

No post-hoc rotation, scaling, XYZ edits or fitted-path substitution. The
existing ICP objective remains authoritative outside its numerical tie band.
"""
import numpy as np


def canonical_principal_basis(points):
    _, _, basis = np.linalg.svd(points-points.mean(0), full_matrices=False)
    result = basis.T.copy()
    # CAD/source coordinate-axis references determine the hemisphere, not LAPACK.
    for column in range(2):
        axis = result[:,column]
        pivot = int(np.argmax(np.abs(axis)))
        if axis[pivot] < 0:
            result[:,column] *= -1
    # Complete a right-handed frame; the null-space sign is never a convention.
    result[:,2] = np.cross(result[:,0],result[:,1])
    return result


def _transverse(axis, references):
    for reference in references:
        vector = np.asarray(reference,dtype=float)
        vector -= axis*np.dot(axis,vector)
        length = np.linalg.norm(vector)
        if length > 1e-8:
            return vector/length
    raise ValueError('Cannot resolve transverse fixture reference')


def registration_preference(source, rotation, translation):
    direction = source[-1]-source[0]
    if np.linalg.norm(direction) < 1e-8:
        direction = canonical_principal_basis(source)[:,0]
    direction = direction/np.linalg.norm(direction)
    mapped = rotation@direction
    source_normal = _transverse(direction, ([0,0,1],[0,1,0],[1,0,0]))
    # Native contact placement already uses CAD up/front. Ordered source motion
    # prefers up, then front, then right for indistinguishable opposite fits.
    # Roll uses source up against CAD front projected perpendicular to motion.
    target_normal = _transverse(mapped, ([0,-1,0],[1,0,0],[0,0,1]))
    tangent = np.round(mapped,6)
    roll = round(float((rotation@source_normal)@target_normal),10)
    center = np.round(source.mean(0)@rotation.T+translation,6)
    return (float(tangent[2]),float(-tangent[1]),float(tangent[0]),roll,
            float(center[2]),float(-center[1]),float(center[0]),
            *np.round(rotation,10).ravel().tolist())


def prefer_registration(score, preference, best):
    if best is None:
        return True
    tolerance = 1e-10*max(1.,abs(score),abs(best[0]))
    if score < best[0]-tolerance:
        return True
    return abs(score-best[0]) <= tolerance and preference > best[3]


def deterministic_rigid_fit(source, target):
    covariance=(source-source.mean(0)).T@(target-target.mean(0))
    u,s,vt=np.linalg.svd(covariance)
    if s[0] < 1e-12:
        return np.eye(3),target.mean(0)-source.mean(0)
    if s[1] <= 1e-12*s[0]:
        # Collinear correspondences constrain tangent, not roll. Preserve the
        # incoming fit's roll with the minimum rotation between tangents.
        direction=canonical_principal_basis(target)[:,0]
        original=covariance@direction
        original/=np.linalg.norm(original)
        cross=np.cross(original,direction)
        cosine=float(np.clip(original@direction,-1.,1.))
        if cosine < -1+1e-10:
            axis=_transverse(original,([0,-1,0],[1,0,0],[0,0,1]))
            rotation=2*np.outer(axis,axis)-np.eye(3)
        else:
            x,y,z=cross
            skew=np.array([[0,-z,y],[z,0,-x],[-y,x,0]])
            rotation=np.eye(3)+skew+skew@skew/(1+cosine)
    else:
        correction=np.eye(3)
        correction[-1,-1]=np.linalg.det(vt.T@u.T)
        rotation=vt.T@correction@u.T
    return rotation,target.mean(0)-rotation@source.mean(0)


def deterministic_nearest(tree, points):
    distance,indices=tree.query(points,k=2)
    nearest=indices[:,0].copy()
    tolerance=1e-10*np.maximum(1.,distance[:,0])
    for row in np.flatnonzero(distance[:,1]-distance[:,0] <= tolerance):
        candidates=tree.query_ball_point(points[row],distance[row,0]+tolerance[row])
        # Equidistant CAD contacts use the native coordinate references, rather
        # than a KD-tree/LAPACK-dependent visit order (right, then up/front).
        nearest[row]=max(candidates,key=lambda i:tuple(tree.data[i][[0,2,1]]* [1,1,-1]))
    return np.linalg.norm(points-tree.data[nearest],axis=1),nearest


def registration_update(source,target,rotation,translation):
    transformed=source@rotation.T+translation
    update,shift=deterministic_rigid_fit(transformed,target)
    rotation,translation=update@rotation,update@translation+shift
    singular=np.linalg.svd((source-source.mean(0)).T@(target-target.mean(0)),compute_uv=False)
    if singular[0]>1e-12 and singular[1]<=1e-12*singular[0]:
        # The unconstrained transverse sign uses the same CAD front reference
        # as the native fixture. Preserve the fit's measured roll magnitude.
        axis=canonical_principal_basis(source)[:,0]
        side=_transverse(axis,([0,0,1],[0,1,0],[1,0,0]))
        mapped_axis=rotation@axis
        mapped_side=rotation@side
        front=_transverse(mapped_axis,([0,-1,0],[1,0,0],[0,0,1]))
        if mapped_side@front < 0:
            mapped_side=-mapped_side
            source_frame=np.column_stack((axis,side,np.cross(axis,side)))
            target_frame=np.column_stack((mapped_axis,mapped_side,np.cross(mapped_axis,mapped_side)))
            rotation=target_frame@source_frame.T
            translation=target.mean(0)-rotation@source.mean(0)
    return rotation,translation
