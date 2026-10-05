"""Pre-change native evaluation exporter, parity fixture only; never production."""
def export(source, destination, metadata, start, points, modes, corner_indices, available, stages, end_conditioned=False, c=None):
    with np.load(source / 'trajectory.npz', allow_pickle=False) as data:
        gt_m = np.asarray(data['ground_truth_path_m'], dtype=float)
        baseline_pred = np.asarray(data['predicted_path_m'], dtype=float) * 1000
    prediction = start + points
    original_gt_m = gt_m.copy()
    gt = gt_m * 1000
    if len(prediction) != len(gt):
        gt = uniform_arc(gt, len(prediction))
        baseline_pred = uniform_arc(baseline_pred, len(prediction))
        gt_m = gt * 0.001
    scores = metrics(prediction, gt)
    baseline_scores = metrics(baseline_pred, gt)
    np.savez_compressed(destination / 'trajectory.npz', predicted_path_m=prediction * 0.001, ground_truth_path_m=gt_m, predicted_path_xyz=prediction, ground_truth_path_xyz=gt, start_xyz=start, predicted_delta_xyz=np.diff(prediction, axis=0), ground_truth_delta_xyz=np.diff(gt, axis=0), corner_indices=corner_indices, connections=modes, original_ground_truth_path_m=original_gt_m)
    for name, values in [('predicted_path_source', prediction), ('predicted_path_m', prediction * 0.001), ('ground_truth_path_source', gt), ('ground_truth_path_m', gt_m)]:
        np.savetxt(destination / f'{name}.csv', values, delimiter=',', header='x,y,z', comments='')
    output = {'episode_id': metadata['episode_id'], 'export_index': metadata.get('export_index'), 'split': source_split(metadata), 'instruction': metadata['instruction'], 'source_units': 'mm', 'scale_to_meters': 0.001, 'coordinate_frame': 'source_robot_frame_unaligned_with_isaac', 'start_xyz': start.tolist(), 'action_definition': f'{len(prediction) - 1} local delta-XYZ actions', 'output_points': len(prediction), 'rough_points_requested': (c or {}).get('rough_points', 9), 'gt_resampling': 'uniform_arc' if len(original_gt_m) != len(prediction) else 'unchanged', 'method': 'GPT rough path + GPT corners + fixed Python linear interpolation', 'stages': stages, 'export_version': PROMPT_VERSION, 'mask_policy': 'all_available_gt_seam_annotations', 'available_mask_views': available, 'gt_path_used_as_model_input': end_conditioned, 'gt_endpoint_used_as_model_input': end_conditioned, 'gt_interior_path_used_as_model_input': False, 'model_family': 'GPT6-Luna-End' if end_conditioned else 'GPT6-Luna', 'conditioning': 'baseline instruction and known start XYZ' + (' + GT endpoint XYZ' if end_conditioned else ''), 'metrics': scores, 'baseline_metrics_on_same_gt': baseline_scores, 'baseline_directory': str(source.resolve()), 'files': {'npz': f'{destination.name}/trajectory.npz'}}
    if end_conditioned:
        output.update(known_end_xyz_mm=gt[-1].tolist(), known_end_offset_mm=(gt[-1] - start).tolist(), endpoint_source='baseline ground_truth_path_m[-1]', endpoint_snapped=False, evaluation_note='GT endpoint is an input; FDE measures endpoint adherence, not unseen endpoint prediction.')
    c = c or {}
    output.update(ablation=ablation(c), experiment=experiment_name(c), mask_policy='none' if c.get('no_mask') else 'all_available_gt_seam_annotations', query_mask_used_as_input=not c.get('no_mask', False), rough_stage_used=not c.get('no_rough', False), retrieval_used=not c.get('no_retrieval', False))
    if c.get('cot_plan'):
        output.update(mask_policy='approved_predicted_masks', cot_session=c['cot_session'], instruction=c['cot_plan']['refined_task']['refined_instruction_en'], rough_stage_used=False, method='Approved project2 reference plan + GPT corners + interpolation')
    if c.get('no_rough'):
        output['method'] = 'GPT direct control points + fixed Python linear interpolation'
    write_json(destination / 'metadata.json', output)
