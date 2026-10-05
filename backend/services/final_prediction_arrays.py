"""Exact native 33-point numeric export, no coordinate correction or playback."""
import io
import numpy as np
from backend.model_clients.trajectory_contracts import GPTPredictedTrajectory


def verify_gpt_arrays(attempt, response, manifest):
    import h5py
    value=GPTPredictedTrajectory.model_validate(response)
    with np.load(io.BytesIO((attempt/'trajectory.npz').read_bytes()),allow_pickle=False) as arrays:
        if set(arrays.files)!={'predicted_path_m','ground_truth_path_m'}:raise ValueError('GPT NPZ schema')
        for key,points in (('predicted_path_m',value.predicted_path_xyz_mm),('ground_truth_path_m',value.ground_truth_path_xyz_mm)):
            expected=np.asarray(points,dtype=np.float64)*.001
            if arrays[key].dtype!=np.float64 or arrays[key].shape!=(33,3) or not np.array_equal(arrays[key],expected):
                raise ValueError('Native XYZ byte/value contract differs')
    # Exact sample evaluation target, never GT substitution in prediction.
    with h5py.File(manifest['h5'],'r') as handle:source=np.asarray(handle['trajectory'][:,:3],dtype=float)
    if len(source)<2 or not np.isfinite(source).all():raise ValueError('GT source invalid')
    gt=np.column_stack([np.interp(np.linspace(0,len(source)-1,33),np.arange(len(source)),source[:,i]) for i in range(3)])
    if not np.array_equal(gt,np.asarray(value.ground_truth_path_xyz_mm)):raise ValueError('GPT GT/H5 differs')
    errors=np.linalg.norm(np.asarray(value.predicted_path_xyz_mm)-gt,axis=1)
    if not np.allclose([errors.mean(),errors[-1]],[value.ade_mm,value.fde_mm],rtol=1e-10,atol=1e-10):raise ValueError('GPT metrics differ')
    return value
