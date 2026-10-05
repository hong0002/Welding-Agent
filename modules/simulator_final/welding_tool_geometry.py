"""Rigid flange-mounted ATU01035 geometry, in robot TCP coordinates."""
import numpy as np

# Rear circular mounting face: mesh ring spans +/-22.80257 mm at Z=-8.4 mm.
# Its centre is (0,0,-8.4), not the earlier PCA extremity estimate.
CAD_MOUNT_LOCAL_MM = np.array([0., 0., -8.4])
CAD_TIP_LOCAL_MM = np.array([0.1407694603715624, 20.39885629926409, 425.4869384765625])


def mounted_cad_transform():
    # CAD mount normal +Z -> robot flange outward -Y. No scaling/deformation.
    rotation = np.array([[1.,0.,0.],[0.,0.,-1.],[0.,1.,0.]])
    transform = np.eye(4)
    transform[:3,:3] = rotation
    transform[:3,3] = -rotation @ (CAD_MOUNT_LOCAL_MM*.001)
    return transform


def mounted_tip_transform():
    # Tip reference axes parallel to the flange; CAD nozzle angle stays intact.
    transform = np.eye(4)
    transform[:3,3] = (mounted_cad_transform() @ np.r_[CAD_TIP_LOCAL_MM*.001,1.])[:3]
    return transform
