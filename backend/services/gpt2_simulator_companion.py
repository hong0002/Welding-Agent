"""Owned simulator-only diagnostic companion; native prediction stays unchanged.

simulator_final's unmodified reader requires matching GT for frame diagnostics.
This GT comes from the bound H5, never from the predictor or fabricated arrays.
Only diagnostic GT is index-resampled; prediction arrays are copied exactly.
"""
import io
from pathlib import Path
import h5py
import numpy as np
from backend.services.gpt2_prediction_proof import PREDICTION_KEYS, sha


def diagnostic_gt(h5,count):
    with h5py.File(h5,'r') as f:
        data=f['trajectory']
        if data.ndim!=2 or data.shape[0]<2 or data.shape[1]<3:
            raise ValueError('Simulator diagnostic H5 invalid')
        xyz=np.asarray(data[:,:3],dtype=float)
    if not np.isfinite(xyz).all(): raise ValueError('Simulator diagnostic H5 nonfinite')
    return np.column_stack([np.interp(np.linspace(0,len(xyz)-1,count),np.arange(len(xyz)),xyz[:,i])*.001 for i in range(3)])


def write_companion(episode,source_bytes,h5):
    episode=Path(episode)
    with np.load(io.BytesIO(source_bytes),allow_pickle=False) as z:
        if set(z.files)!=PREDICTION_KEYS: raise ValueError('Prediction-only schema differs')
        arrays={k:z[k] for k in z.files}
    native=episode/'native_prediction.npz'
    with native.open('xb') as f: f.write(source_bytes)
    arrays['ground_truth_path_m']=diagnostic_gt(h5,len(arrays['predicted_path_m']))
    with (episode/'trajectory.npz').open('xb') as f: np.savez_compressed(f,**arrays)
    return dict(schema='gpt2-simulator-diagnostic-companion-v1',native_prediction_sha256=sha(native),
                simulator_input_sha256=sha(episode/'trajectory.npz'),h5_sha256=sha(h5),
                gt_source='exact_current_sample_h5',gt_role='simulator_frame_diagnostic_only',
                gt_resampling='index',prediction_xyz_modified=False,gt_is_robot_target=False)


def verify_companion(episode,source,h5,receipt):
    episode,source=Path(episode),Path(source)
    if (receipt['schema']!='gpt2-simulator-diagnostic-companion-v1' or
            receipt['gt_source']!='exact_current_sample_h5' or receipt['gt_role']!='simulator_frame_diagnostic_only' or
            receipt['gt_resampling']!='index' or receipt['prediction_xyz_modified'] is not False or
            receipt['gt_is_robot_target'] is not False or
            sha(h5)!=receipt['h5_sha256'] or sha(source)!=receipt['native_prediction_sha256'] or
            sha(episode/'native_prediction.npz')!=sha(source) or
            sha(episode/'trajectory.npz')!=receipt['simulator_input_sha256']):
        raise ValueError('Simulator companion provenance differs')
    with np.load(source,allow_pickle=False) as a,np.load(episode/'trajectory.npz',allow_pickle=False) as b:
        if set(a.files)!=PREDICTION_KEYS or set(b.files)!=PREDICTION_KEYS|{'ground_truth_path_m'}:
            raise ValueError('Simulator companion schema differs')
        if any(not np.array_equal(a[k],b[k]) or a[k].dtype!=b[k].dtype for k in a.files):
            raise ValueError('Simulator companion prediction changed')
        if not np.array_equal(b['ground_truth_path_m'],diagnostic_gt(h5,len(a['predicted_path_m']))):
            raise ValueError('Simulator diagnostic GT differs from bound H5')
