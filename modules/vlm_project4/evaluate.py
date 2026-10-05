#!/usr/bin/env python3
"""Read-only evaluation of saved exports. No model, API, SSH or simulator imports."""
import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

WORKSPACE = Path(__file__).resolve().parent.parent
STAGES = ('rough_native', 'final_native', 'final_9', 'final_33')
# Known experiment conditions for legacy exports without endpoint flags.
# Exact names only: do not guess conditions for newly added experiments.
LEGACY_ENDPOINT_CONDITIONS = {
    ('OpenVLA', 'welding_validation_best_all'): False,
    ('OpenVLA', 'welding_validation_filtered_v2_best_all'): False,
    ('OpenVLA', 'welding_validation_maskmix_best_available'): False,
    ('RICL', 'welding_validation_ricl_all'): False,
    ('RICL', 'welding_validation_ricl_maskmix_available'): False,
    ('RICL', 'welding_validation_ricl_maskmix_endpoint_available'): True,
    ('RICL', 'welding_validation_ricl_endpoint_nomask'): True,
}


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def path_array(value, count=None):
    p = np.asarray(value, dtype=np.float64)
    if p.ndim != 2 or p.shape[1] != 3 or len(p) < 2 or not np.isfinite(p).all():
        raise ValueError('expected finite Nx3 XYZ, N >= 2')
    if count is not None and len(p) != count:
        raise ValueError(f'expected {count} points, found {len(p)}')
    return p


def errors(pred, gt):
    if pred.shape != gt.shape:
        raise ValueError('prediction and GT shapes differ')
    e = np.linalg.norm(pred - gt, axis=1)
    return dict(ade_mm=float(e.mean()), fde_mm=float(e[-1]), pre_end_mm=float(e[-2]))


def gt_at_rough_progress(rough, gt):
    """Compare native corners at their own normalized cumulative path lengths."""
    d = np.r_[0., np.cumsum(np.linalg.norm(np.diff(rough, axis=0), axis=1))]
    t = d / d[-1] if d[-1] > 0 else np.linspace(0., 1., len(rough))
    g = np.r_[0., np.cumsum(np.linalg.norm(np.diff(gt, axis=0), axis=1))]
    g, indices = np.unique(g, return_index=True)
    return np.column_stack([np.interp(t * g[-1], g, gt[indices, axis]) for axis in range(3)])


def under(path, roots):
    return any(path == root or root in path.parents for root in roots)


def endpoint_group(directory, meta, yes, no):
    explicit = meta.get('gt_endpoint_used_as_model_input')
    if type(explicit) is not bool:
        explicit = None
    manifest = directory / 'input_manifest.json'
    if manifest.exists():
        m = read_json(manifest)
        value = m.get('gt_endpoint_used_as_input')
        if type(value) is bool:
            if explicit is not None and value != explicit:
                raise ValueError('conflicting endpoint flags')
            explicit = value
    # Legacy GPT exports predate the dedicated endpoint flag.
    if explicit is None and meta.get('conditioning') == 'baseline instruction and known start XYZ':
        explicit = False
    override = True if under(directory, yes) else False if under(directory, no) else None
    if override is not None:
        if explicit is not None and explicit != override:
            raise ValueError('endpoint override conflicts with saved input condition')
        return ('END' if override else 'NO-END'), 'user override'
    if explicit is not None:
        return ('END' if explicit else 'NO-END'), 'saved input condition'
    export = directory.parent
    known = LEGACY_ENDPOINT_CONDITIONS.get((export.parent.name, export.name))
    if known is not None:
        return ('END' if known else 'NO-END'), 'known legacy experiment condition'
    return 'UNKNOWN', 'endpoint input not recorded; use --no-end-export or --end-export'


def discover(roots):
    exports = set()
    for root in roots:
        if not root.is_dir():
            continue
        for p in root.rglob('metadata.json'):
            if (p.parent / 'trajectory.npz').is_file():
                exports.add(p.parent.parent)
    return sorted(exports)


def load_export(root, yes, no, selected):
    rows, issues, seen = [], [], set()
    for file in sorted(root.glob('*/metadata.json')):
        directory = file.parent
        try:
            meta = read_json(file)
            sid = meta['episode_id']
            if selected and sid not in selected:
                continue
            if str(meta.get('split', '')).lower() not in ('val', 'valid', 'validation'):
                continue
            status = directory / 'status.json'
            if status.exists() and read_json(status).get('status') != 'complete':
                issues.append(f'{directory.name}: incomplete; skipped')
                continue
            if sid in seen:
                raise ValueError(f'duplicate episode ID: {sid}')
            group, provenance = endpoint_group(directory, meta, yes, no)
            with np.load(directory / 'trajectory.npz', allow_pickle=False) as data:
                pred = path_array(data['predicted_path_m']) * 1000.
                gt = path_array(data['ground_truth_path_m'], len(pred)) * 1000.
                rough_gt = path_array(data['original_ground_truth_path_m']) * 1000. if 'original_ground_truth_path_m' in data else gt
            stages = {f'final_{len(pred)}' if len(pred) in (9,33) else 'final_native': errors(pred, gt)}
            row = dict(sample_id=sid, group=group, condition_source=provenance,
                       experiment=meta.get('experiment','full'), ablation=meta.get('ablation',{}),
                       frame=meta.get('coordinate_frame'), gt=gt,
                       final_points=len(pred), stages=stages)
            rough_file = directory / 'rough.json'
            if rough_file.exists():
                try:
                    response = read_json(rough_file)
                    if 'end_conditioned' in response and group != 'UNKNOWN':
                        if bool(response['end_conditioned']) != (group == 'END'):
                            raise ValueError('rough endpoint condition differs from final export')
                    committed_id = meta.get('stages', {}).get('rough', {}).get('response_id')
                    if committed_id and response.get('response_id') != committed_id:
                        raise ValueError('rough response is newer than committed final export')
                    proposal = response['proposal']
                    offsets = path_array([[p[a] for a in ('x', 'y', 'z')] for p in proposal['points']])
                    if meta.get('source_units') != 'mm':
                        raise ValueError('rough offsets require declared mm units')
                    start = np.asarray(meta['start_xyz'], dtype=float)
                    if start.shape != (3,) or not np.isfinite(start).all():
                        raise ValueError('invalid supplied start')
                    rough = offsets + start
                    row['rough_points'] = len(rough)
                    row['stages']['rough_native'] = errors(rough, gt_at_rough_progress(rough, rough_gt))
                except (ValueError, KeyError, TypeError, OSError) as exc:
                    issues.append(f'{directory.name}: rough unavailable: {exc}')
            rows.append(row)
            seen.add(sid)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            issues.append(f'{directory.name}: {exc}')
    return rows, issues


def mean_metrics(rows, stage):
    values = [r['stages'][stage] for r in rows if stage in r['stages']]
    return dict(n=len(values), **{
        k: float(np.mean([v[k] for v in values])) if values else None
        for k in ('ade_mm', 'fde_mm', 'pre_end_mm')})


def ablation_sort_key(item):
    name, rows = item
    flags = rows[0].get('ablation', {}) if rows else {}
    if flags:
        removed = frozenset(k.replace('_', '-') for k, v in flags.items() if v)
    else:
        removed = frozenset(Path(name).name.split('__')[1:])
    order = (
        frozenset(), frozenset({'no-mask'}), frozenset({'no-rough'}),
        frozenset({'no-retrieval'}), frozenset({'no-mask', 'no-rough'}),
        frozenset({'no-mask', 'no-retrieval'}), frozenset({'no-rough', 'no-retrieval'}),
        frozenset({'no-mask', 'no-rough', 'no-retrieval'}),
    )
    return (order.index(removed) if removed in order else len(order), name)


def table_line(name, stage, result, original=None):
    nums = [f'{result[k]:.3f}' if result[k] is not None else 'N/A'
            for k in ('ade_mm', 'fde_mm', 'pre_end_mm')]
    if original is not None:
        before = [f'{original[k]:.3f}' if original[k] is not None else 'N/A'
                  for k in ('ade_mm', 'fde_mm', 'pre_end_mm')]
        nums = [f'{value} ({old})' for value, old in zip(nums, before)]
        count = f'{result["n"]} ({original["n"]})'
        print(f'{name:<68} {stage:<13} {count:>11}  ' + '  '.join(f'{n:>19}' for n in nums))
        return
    print(f'{name:<68} {stage:<13} {result["n"]:>4}  ' + '  '.join(f'{n:>11}' for n in nums))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--roots', type=Path, nargs='+', default=[
        WORKSPACE / name for name in ('GPT6-Luna', 'GPT6-Luna-End', 'OpenVLA', 'RICL')])
    parser.add_argument('--end-export', type=Path, nargs='+', default=[], help='declare endpoint input for legacy exports')
    parser.add_argument('--no-end-export', type=Path, nargs='+', default=[], help='declare no endpoint input for legacy exports')
    parser.add_argument('--id', nargs='+', help='optional sample IDs')
    parser.add_argument('--list', action='store_true', help='print unique validation categories, e.g. L_PR, T_SS')
    parser.add_argument('--x', nargs='+', default=[], help='also evaluate excluding sample IDs or prefixes, e.g. T_SS T_PR')
    parser.add_argument('--common', action='store_true', help='also show pairwise common-sample comparisons')
    parser.add_argument('--json', type=Path, help='optional report path; otherwise only print results')
    args = parser.parse_args()
    yes, no = [[p.resolve() for p in paths] for paths in (args.end_export, args.no_end_export)]
    if any(under(p, no) for p in yes) or any(under(p, yes) for p in no):
        parser.error('endpoint overrides overlap')
    roots = discover([p.resolve() for p in args.roots])
    if not roots:
        parser.error('no exported metadata.json + trajectory.npz found')
    excluded_prefixes = tuple(dict.fromkeys(
        token.strip() for value in args.x for token in value.split(',') if token.strip()))

    def excluded(sid):
        return any(sid == prefix or sid.startswith(prefix.rstrip('_') + '_')
                   for prefix in excluded_prefixes)

    if args.list:
        sample_ids = set()
        for root in roots:
            for file in root.glob('*/metadata.json'):
                meta = read_json(file)
                sid = meta.get('episode_id')
                if (sid and str(meta.get('split', '')).lower() in ('val', 'valid', 'validation')
                        and (not args.id or sid in args.id) and not excluded(sid)):
                    sample_ids.add(sid)
        print('\n'.join(sorted({'_'.join(sid.split('_')[:2]) for sid in sample_ids})))
        return
    groups = defaultdict(dict)
    display_groups = defaultdict(dict)
    report = dict(units='mm', ade_includes_start=True, exports={}, comparisons=[],
                  excluded_prefixes=list(excluded_prefixes), filtered_exports={})
    for root in roots:
        name = str(root.relative_to(WORKSPACE)) if root.is_relative_to(WORKSPACE) else str(root)
        rows, issues = load_export(root, yes, no, set(args.id or []))
        report['exports'][name] = dict(issues=issues, samples=[
            {k: v for k, v in row.items() if k != 'gt'} for row in rows])
        if excluded_prefixes:
            kept = [r for r in rows if not excluded(r['sample_id'])]
            report['filtered_exports'][name] = dict(
                excluded_sample_ids=[r['sample_id'] for r in rows if excluded(r['sample_id'])],
                remaining_sample_ids=[r['sample_id'] for r in kept],
                metrics={stage: mean_metrics(kept, stage) for stage in STAGES
                         if any(stage in r['stages'] for r in rows)})
        for group in ('NO-END', 'END', 'UNKNOWN'):
            subset = [r for r in rows if r['group'] == group]
            if subset:
                groups[group][name] = subset
                family = 'GPT' if root.parent.name in ('GPT6-Luna', 'GPT6-Luna-End') else 'OpenVLA / RICL'
                display_groups[(family, group)][name] = subset
        for issue in issues[:3]:
            print(f'[SKIP] {name}: {issue}')
        if len(issues) > 3:
            print(f'[SKIP] {name}: {len(issues)} issues total; --json saves full details')

    print('Unit: mm')
    if excluded_prefixes:
        print('Values: excluded result (original ALL result)')
    for family in ('GPT', 'OpenVLA / RICL'):
        for group in ('NO-END', 'END', 'UNKNOWN'):
            exports = display_groups[(family, group)]
            if not exports:
                continue
            filtered = bool(excluded_prefixes)
            title = 'EXCLUDE ' + ', '.join(excluded_prefixes) if filtered else 'ALL available samples (counts may differ)'
            print(f'\n[{family} | {group}] {title}')
            if filtered:
                print(f'{"Export":<68} {"Stage":<13} {"N":>11}  {"ADE":>19}  {"FDE":>19}  {"PRE-END":>19}')
            else:
                print(f'{"Export":<68} {"Stage":<13} {"N":>4} {"ADE":>13} {"FDE":>13} {"PRE-END":>13}')
            ordered = sorted(exports.items(), key=ablation_sort_key) if family == 'GPT' else exports.items()
            for name, rows in ordered:
                evaluated = [r for r in rows if not excluded(r['sample_id'])] if filtered else rows
                for stage in STAGES:
                    if any(stage in r['stages'] for r in rows):
                        table_line(name, stage, mean_metrics(evaluated, stage),
                                   mean_metrics(rows, stage) if filtered else None)
    for group in ('NO-END', 'END'):
        exports = groups[group]
        if not args.common or not exports:
            continue
        # Pairwise common subsets avoid reducing every comparison to a small representative export.
        names = list(exports)
        for i, left in enumerate(names):
            for right in names[i + 1:]:
                a = {r['sample_id']: r for r in exports[left]}
                b = {r['sample_id']: r for r in exports[right]}
                shared = sorted(a.keys() & b.keys())
                matched = [s for s in shared if a[s]['frame'] is not None
                           and a[s]['frame'] == b[s]['frame']
                           and a[s]['gt'].shape == b[s]['gt'].shape
                           and np.max(np.linalg.norm(a[s]['gt'] - b[s]['gt'], axis=1)) <= 0.01]
                print(f'\n[{group} COMMON] {left} vs {right}: N={len(matched)}; '
                      f'GT/frame mismatch excluded={len(shared)-len(matched)}')
                comparison = dict(group=group, left=left, right=right, sample_ids=matched,
                                  gt_mismatch_ids=sorted(set(shared)-set(matched)), metrics={})
                for name, samples in ((left, a), (right, b)):
                    comparison['metrics'][name] = {}
                    for stage in STAGES:
                        # Each stage reports its own usable count within the common subset.
                        result = mean_metrics([samples[s] for s in matched], stage)
                        if result['n']:
                            table_line(name, stage, result)
                            comparison['metrics'][name][stage] = result
                report['comparisons'].append(comparison)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        print(f'[SAVE] {args.json}')


if __name__ == '__main__':
    main()
