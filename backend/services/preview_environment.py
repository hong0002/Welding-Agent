"""Render native saved STP environment dimensions; never fit/translate a sample."""
import numpy as np


def stp_primitives(native):
    if str(native['environment_layout']) != 'stp':
        raise ValueError('Native STP layout missing')
    floor = float(native['environment_floor_z_m'])
    top = float(native['fixture_table_top_m'])
    center = np.asarray(native['environment_table_center_xy_m'])
    size = np.asarray(native['environment_table_size_xy_m'])
    if (center.shape != (2,) or size.shape != (2,) or
            not np.isfinite([floor,top,*center,*size]).all() or
            floor >= 0 or top-.04 <= floor or np.any(size <= .06)):
        raise ValueError('Invalid native environment dimensions')
    # Same cube topology as the native renderer. All placement values come from
    # apply_environment's saved arrays; source_to_scene/workpiece are untouched.
    result = [('Ground',[0,0,floor-.025],[3,3,.05]),
              ('RobotPedestal',[0,0,floor/2],[.600,.800,-floor]),
              ('ReferenceTable',[*center,top-.02],[*size,.04])]
    for i, (sx,sy) in enumerate(((-1,-1),(-1,1),(1,-1),(1,1))):
        xy = center+np.array([sx,sy])*(size/2-.03)
        result.append(('TableLeg'+str(i),[*xy,(top-.04+floor)/2],
                       [.025,.025,top-.04-floor]))
    return result
