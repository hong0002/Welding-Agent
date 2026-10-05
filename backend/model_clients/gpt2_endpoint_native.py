"""Supplied-endpoint interface to the unchanged native prediction-only pipeline.

Only endpoint context/prompt/export metadata are extended. Original stages,
Proposal, start addition and interpolate_corners execute unchanged. No GT loader.
"""
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np


def endpoint_diagnostics(endpoint, start, prediction):
    return dict(endpoint_conditioned=True,
        start_source='dataset_known_start' if endpoint['source']=='dataset_gt_endpoint' else 'existing_known_start',
        end_source=endpoint['source'], start_xyz_mm=np.asarray(start).tolist(), end_xyz_mm=endpoint['end_xyz_mm'],
        end_binding_hash=endpoint['binding_hash'],
        start_error_mm=float(np.linalg.norm(prediction[0]-start)),
        end_error_mm=float(np.linalg.norm(prediction[-1]-endpoint['end_xyz_mm'])),
        xyz_posthoc_snapped=False, xyz_modified_by_adapter=False,
        blind_prediction=False if endpoint['source']=='dataset_gt_endpoint' else True)


def install_endpoint(native, endpoint):
    end = np.asarray(endpoint['end_xyz_mm'], dtype=float)
    if end.shape != (3,) or not np.isfinite(end).all() or endpoint['sample_id'] != 'B_PR_03_0001':
        raise ValueError('GPT2_ENDPOINT_INVALID')
    gt = endpoint['source'] == 'dataset_gt_endpoint'
    original_prompt, original_input, original_export = native.prompt_for_mode, native.input_content, native.export_prediction_only

    def supplied_endpoint(source, start, enabled=False):
        # Never call original endpoint_context: it reads baseline query GT NPZ.
        return dict(known_end_xyz_mm=end.tolist(), known_end_offset_mm=(end-start).tolist(),
            endpoint_source=endpoint['source'], absolute_endpoint_frame=endpoint['coordinate_frame'], endpoint_units='mm')

    def prompt(end_conditioned=False, c=None):
        value = original_prompt(True, c)
        if not gt:
            value = value.replace('Only the query GT endpoint is supplied as an explicit experimental input; interior GT points are not provided.',
                                  'A user-selected endpoint is supplied explicitly; query GT trajectory is not provided.')
        return value

    def inputs(source, destination, metadata, c):
        if metadata['episode_id'] != endpoint['sample_id']:
            raise ValueError('GPT2_ENDPOINT_SAMPLE_CHANGED')
        result = original_input(source, destination, metadata, c)
        file = destination/'input_manifest.json'
        manifest = json.loads(file.read_text(encoding='utf-8'))
        manifest.update(endpoint_conditioned=True, endpoint_source=endpoint['source'], end_binding_hash=endpoint['binding_hash'],
            gt_path_used_as_input=gt, gt_endpoint_used_as_input=gt, gt_interior_path_used_as_input=False,
            conditioning_note='Known start and explicitly supplied '+endpoint['source']+'; no query interior trajectory.')
        native.write_json(file, manifest)
        return result

    def export(destination, metadata, start, prediction, modes, corner_indices, available, stages, c):
        original_export(destination, metadata, start, prediction, modes, corner_indices, available, stages, c)
        file = destination/'metadata.json'
        meta = json.loads(file.read_text(encoding='utf-8'))
        meta.update(endpoint_diagnostics(endpoint, start, prediction),
            gt_path_used_as_model_input=gt, gt_endpoint_used_as_model_input=gt,
            gt_interior_path_used_as_model_input=False,
            conditioning='query instruction, known start XYZ and explicitly supplied '+endpoint['source'])
        native.write_json(file, meta)

    native.endpoint_context = supplied_endpoint
    native.prompt_for_mode = prompt
    native.input_content = inputs
    native.export_prediction_only = export


def run_with_endpoint(repository, endpoint_file):
    # Fixed backend-owned file, not a browser-supplied path or Python module.
    endpoint = json.loads(Path(endpoint_file).read_text(encoding='utf-8'))
    spec = importlib.util.spec_from_file_location('owned_gpt2_endpoint_native', Path(repository)/'predict.py')
    native = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = native
    spec.loader.exec_module(native)
    install_endpoint(native, endpoint)
    return native.main()
