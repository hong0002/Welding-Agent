"""Fixed, model-independent piecewise-linear interpolation. Never executes GPT code."""
import numpy as np


def normalize_connections(connections, point_count):
    """Connection tags are annotations, not a prerequisite for XYZ interpolation.

    A singleton within_segment is a whole-path continuous annotation. Ambiguous
    lists are marked unknown; never invent the locations of disconnected seams.
    """
    raw = list(connections or [])
    edges = max(0, point_count - 1)
    allowed = ('within_segment', 'between_segments', 'unknown')
    if len(raw) == edges and all(v in allowed for v in raw):
        values, policy = raw, 'as_returned'
    elif raw == ['within_segment']:
        values, policy = ['within_segment'] * edges, 'broadcast_continuous_path'
    else:
        values, policy = ['unknown'] * edges, 'ambiguous_annotations_unknown'
    return values, {'raw_connections': raw, 'normalized_connections': values,
                    'policy': policy, 'xyz_modified': False}


def interpolate_corners(corners, edge_modes, count=33):
    """Keep every supplied corner, apportion extra intervals by edge length.

    Returns points, original-corner indices, and one mode per output interval.
    Between-segment edges encode gaps in the fixed-size path, not welding states.
    """
    p = np.asarray(corners, dtype=np.float64)
    if p.ndim != 2 or p.shape[1] != 3 or not 2 <= len(p) <= count or not np.isfinite(p).all():
        raise ValueError(f'expected finite 2..{count} XYZ control points')
    edge_modes, _ = normalize_connections(edge_modes, len(p))
    lengths = np.linalg.norm(np.diff(p, axis=0), axis=1)
    intervals = np.ones(len(lengths),dtype=int)
    extra = count-1-len(lengths)
    # Repeated points are valid (possibly poor) predictions, not a save failure.
    shares = extra*lengths/lengths.sum() if lengths.sum()>0 else np.full(len(lengths),extra/len(lengths))
    intervals += np.floor(shares).astype(int)
    remaining = count-1-int(intervals.sum())
    order = np.argsort(-(shares-np.floor(shares)),kind='stable')
    intervals[order[:remaining]] += 1
    points=[p[0]]; indices=[0]; modes=[]
    for a,b,n,mode in zip(p[:-1],p[1:],intervals,edge_modes):
        points.extend(np.linspace(a,b,int(n)+1)[1:])
        modes.extend([mode]*int(n))
        indices.append(len(points)-1)
    return np.asarray(points), np.asarray(indices), np.asarray(modes)


def uniform_arc(points, count=33):
    points=np.asarray(points,dtype=float)
    d=np.r_[0.,np.cumsum(np.linalg.norm(np.diff(points,axis=0),axis=1))]
    d,indices=np.unique(d,return_index=True)
    if len(d)<2: return np.repeat(points[:1],count,axis=0)
    return np.column_stack([np.interp(np.linspace(0,d[-1],count),d,points[indices,a]) for a in range(3)])


def metrics(predicted_mm, gt_mm):
    p,g=np.asarray(predicted_mm),np.asarray(gt_mm)
    if p.ndim != 2 or p.shape[1] != 3 or len(p)<2 or g.shape != p.shape or not np.isfinite(p).all() or not np.isfinite(g).all():
        raise ValueError('evaluation requires finite matching (N>=2,3) paths')
    errors=np.linalg.norm(p-g,axis=1)
    return {'ade_source_units':float(errors.mean()), 'fde_source_units':float(errors[-1]),
            'max_error_source_units':float(errors.max()),
            'delta_mae_source_units':float(np.abs(np.diff(p,axis=0)-np.diff(g,axis=0)).mean()),
            'predicted_path_length_source_units':float(np.linalg.norm(np.diff(p,axis=0),axis=1).sum()),
            'ground_truth_path_length_source_units':float(np.linalg.norm(np.diff(g,axis=0),axis=1).sum()),
            'uniform_arc_ade_mm':float(np.linalg.norm(uniform_arc(p)-uniform_arc(g),axis=1).mean())}
