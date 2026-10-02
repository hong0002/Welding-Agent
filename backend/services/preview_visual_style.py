"""Display-only style; never changes source points, native playback or transforms."""
def define_polyline(stage, path, points, color, width, *, usd_geom, gf):
    """One connected linear curve. Dependencies injected for offline verification."""
    obj = usd_geom.BasisCurves.Define(stage, path)
    obj.CreateTypeAttr('linear')
    obj.CreateWrapAttr('nonperiodic')
    obj.CreateCurveVertexCountsAttr([len(points)])
    obj.CreatePointsAttr([gf.Vec3f(*map(float, p)) for p in points])
    obj.CreateWidthsAttr([width])
    obj.CreateDisplayColorAttr([gf.Vec3f(*color)])
    return obj


def prediction_style(backend):
    if backend == 'dataset_stp':
        return dict(color=(1., .015, .025), width_m=.006, marker_radius_m=.0018,
                    source_label='red: VLA source XYZ path', playback_label='robot: native derived playback')
    return dict(color=(1., .22, .04), width_m=.003, marker_radius_m=.0035,
                source_label='orange: predicted XYZ', playback_label='robot: native derived playback')
