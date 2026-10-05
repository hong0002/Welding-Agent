"""Audit extracted CAD/H5 data or prepare representative/exported paths without Isaac Sim."""
import argparse
from collections import Counter
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import time

import h5py
import numpy as np

from run_welding_sample import ROOT, DEFAULT_DATA, open_samples, sample_index, prepare
from welding_scene_layout import fixture_supported
from welding_workpiece import load_obj_mesh
from welding_contact_fixture import contact_geometry
from welding_prediction import prediction_index


def source_issue(archive, member):
    try:
        with h5py.File(io.BytesIO(archive.read(member)), 'r') as handle:
            for key in ('trajectory', 'joint_values', 'original_points'):
                data = np.asarray(handle[key])
                if data.ndim != 2 or len(data) < 2 or data.shape[1] not in ((3, 6) if key == 'trajectory' else (6,)):
                    return f'{key}: invalid shape {data.shape}'
                if not np.isfinite(data).all():
                    return f'{key}: source data contains NaN/Inf'
    except (OSError, KeyError, ValueError) as exc:
        return str(exc)
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('geometry', 'representatives', 'predictions'), default='geometry')
    parser.add_argument('--data-root', type=Path, default=DEFAULT_DATA)
    parser.add_argument('--prediction-root', type=Path)
    parser.add_argument('--output-dir', type=Path, default=ROOT/'welding_sample_outputs/fixture_audit')
    args = parser.parse_args()
    if args.mode == 'predictions' and args.prediction_root is None:
        parser.error('--prediction-root is required for prediction checks')
    predictions = prediction_index(args.prediction_root) if args.prediction_root else {}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    started = time.monotonic()
    with open_samples(args.data_root) as archive:
        index = sample_index(archive)
        if args.mode == 'geometry' and not hasattr(archive, 'root'):
            parser.error('Geometry audit currently requires extracted OBJ/H5 files')
        issues = {sample: source_issue(archive, member) for sample, member in index.items()}
        jobs = []
        if args.mode == 'geometry':
            jobs = [(sample, 'geometry') for sample in sorted(index)]
        elif args.mode == 'predictions':
            jobs = [(sample, 'predict') for sample in sorted(predictions)]
        else:
            families = sorted({'_'.join(s.split('_')[:2]) for s in index})
            for family in families:
                candidates = [s for s in sorted(index) if s.startswith(family+'_') and not issues[s]]
                if not candidates:
                    jobs.append((next(s for s in index if s.startswith(family+'_')), 'gt'))
                    continue
                sample = next((s for s in candidates if s in predictions), candidates[0])
                jobs.append((sample, 'gt'))
                if sample in predictions:
                    jobs.append((sample, 'predict'))
        for number, (sample, mode) in enumerate(jobs, 1):
            row = dict(sample=sample, family='_'.join(sample.split('_')[:2]), mode=mode,
                       supported=fixture_supported(sample), source_issue=issues.get(sample))
            try:
                member = index[sample]
                if mode == 'geometry':
                    obj = Path(str(archive.root/member).replace('로봇티칭데이터', '모델링 데이터')).with_suffix('.obj')
                    vertices, counts, indices = load_obj_mesh(obj)
                    contact, gap, _ = contact_geometry(vertices, counts, indices)
                    row.update(ok=True,contact_candidate_count=len(contact),cad_contact_gap_mm=gap)
                else:
                    if row['source_issue']:
                        raise ValueError(row['source_issue'])
                    output = args.output_dir/sample/mode
                    with redirect_stdout(io.StringIO()):
                        solution = prepare(archive, member, output, predictions[sample] if mode == 'predict' else None)
                    row.update(ok=True, solution=str(solution),
                               report=json.loads((output/'report.json').read_text()))
            except Exception as exc:
                row.update(ok=False,error=f'{type(exc).__name__}: {exc}')
            rows.append(row)
            summary = dict(mode=args.mode,completed=len(rows),total=len(jobs),
                           passed=sum(r['ok'] for r in rows),failed=sum(not r['ok'] for r in rows),
                           source_invalid=sum(bool(r['source_issue']) for r in rows),
                           families=dict(Counter(r['family'] for r in rows)),
                           elapsed_sec=time.monotonic()-started)
            result = args.output_dir/f'{args.mode}.json'
            temporary = result.with_suffix('.tmp')
            temporary.write_text(json.dumps(dict(summary=summary,rows=rows),ensure_ascii=False,indent=2))
            temporary.replace(result)
            print(f'[{number}/{len(jobs)}] {sample} {mode}: {"OK" if row["ok"] else row["error"]}',flush=True)
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    print(f'[SAVE] {result}')


if __name__ == '__main__':
    main()
