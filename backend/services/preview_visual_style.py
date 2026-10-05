"""Display-only style; never changes source points, native playback or transforms."""
def define_polyline(stage, path, points, color, width, *, usd_geom, gf):
    """One connected linear curve. Dependencies injected for offline verification."""
    import math
    values = [tuple(map(float, p)) for p in points]
    if not values or any(len(p) != 3 or not all(map(math.isfinite, p)) for p in values):
        return None  # Native admission remains authoritative; never correct XYZ.
    if len(values) == 1:
        obj = usd_geom.Sphere.Define(stage, path)
        obj.CreateRadiusAttr(width / 2)
        obj.AddTranslateOp().Set(gf.Vec3d(*values[0]))
        obj.CreateDisplayColorAttr([gf.Vec3f(*color)])
        return obj
    obj = usd_geom.BasisCurves.Define(stage, path)
    obj.CreateTypeAttr('linear')
    obj.CreateWrapAttr('nonperiodic')
    obj.CreateCurveVertexCountsAttr([len(values)])
    obj.CreatePointsAttr([gf.Vec3f(*p) for p in values])
    obj.CreateWidthsAttr([width])
    obj.SetWidthsInterpolation('constant')
    obj.CreateDisplayColorAttr([gf.Vec3f(*color)])
    return obj


def prediction_style(backend):
    if backend == 'dataset_stp':
        return dict(color=(1., .015, .025), width_m=.006, marker_radius_m=.0018,
                    point_markers=False,
                    source_label='red: final prediction source XYZ path', playback_label='robot: native derived playback')
    return dict(color=(1., .22, .04), width_m=.003, marker_radius_m=.0035,
                point_markers=True,
                source_label='orange: predicted XYZ', playback_label='robot: native derived playback')
