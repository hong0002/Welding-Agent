"""Keyboard menu for the existing two-terminal welding playback queue."""
import curses
import fcntl
import json
import io
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap

from run_welding_sample import ROOT, DEFAULT_DATA, open_samples, sample_index
from welding_command_queue import DEFAULT_QUEUE
from welding_scene_layout import fixture_supported

WORKSPACE = ROOT.parent.parent
SPLITS = {'train': 'Training', 'valid': 'Validation'}


def discover_prediction_roots(workspace=WORKSPACE):
    """Find real exports under model directories, regardless of export folder name."""
    workspace = Path(workspace)
    candidates = list(workspace.glob('welding_*')) + list(workspace.glob('*/welding_*'))
    for family in ('OpenVLA', 'RICL', 'GPT6-Luna', 'GPT6-Luna-End'):
        directory = workspace/family
        if directory.is_dir():
            candidates.extend(meta.parent.parent for meta in directory.rglob('metadata.json')
                              if (meta.parent/'trajectory.npz').is_file()
                              and 'retrieval_bank' not in meta.relative_to(directory).parts)
    valid = {p.resolve() for p in candidates if p.is_dir() and any(
        (meta.parent/'trajectory.npz').is_file() for meta in p.glob('*/metadata.json'))}
    # A copied export can accidentally sit inside another complete export, for example
    # RICL/welding_validation_ricl_all/welding_train_ricl_all.  Its metadata may describe
    # train samples, but presenting that descendant as a separate model export under the Train
    # menu is misleading.  Keep deeply nested experiment exports when their ancestors are not
    # exports themselves, and suppress only descendants of an already valid export root.
    return sorted(root for root in valid if not any(parent in valid for parent in root.parents))


def prediction_family(root, workspace=WORKSPACE):
    try:
        name = Path(root).resolve().relative_to(Path(workspace).resolve()).parts[0]
    except (ValueError, IndexError):
        return 'Other exports'
    return name if name in ('OpenVLA', 'RICL', 'GPT6-Luna', 'GPT6-Luna-End') else 'Other exports'


def prediction_export_label(root, workspace=WORKSPACE):
    try:
        return Path(root).resolve().relative_to(Path(workspace).resolve()).as_posix()
    except ValueError:
        return str(root)


def normalize_split(value):
    return {'train': 'train', 'training': 'train', 'val': 'valid',
            'valid': 'valid', 'validation': 'valid'}.get(str(value).lower())


def error_label(metadata, trajectory_path=None):
    """Exported position errors are distances, not percentages."""
    scale = metadata.get('scale_to_meters')
    if scale is None:
        scale = {'mm': .001, 'm': 1.}.get(metadata.get('source_units'))
    try:
        scale = float(scale) * 1000
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError('Invalid scale')
    except (TypeError, ValueError):
        return '(ADE N/A / FDE N/A / PRE-END N/A)'
    metrics = metadata.get('metrics') or {}
    def value(key):
        try:
            number = float(metrics[key]) * scale
            if math.isfinite(number) and number >= 0:
                return f'{number:.2f} mm'
        except (KeyError, TypeError, ValueError):
            pass
        return 'N/A'
    pre_end = 'N/A'
    if trajectory_path is not None:
        import numpy as np
        from welding_prediction import penultimate_error_mm
        try:
            with np.load(trajectory_path, allow_pickle=False) as data:
                error = penultimate_error_mm(data['predicted_path_m'], data['ground_truth_path_m'])
            pre_end = f'{error:.2f} mm'
        except (OSError, ValueError, KeyError):
            pass
    return f'(ADE {value("ade_source_units")} / FDE {value("fde_source_units")} / PRE-END {pre_end})'


def sample_label(row, mode, prediction_root=None):
    label = row['sample']
    if mode == 'predict':
        label += ' ' + row.get('prediction_metrics', {}).get(prediction_root, '(ADE N/A / FDE N/A / PRE-END N/A)')
    if row.get('source_issue'):
        label += '  [invalid H5]'
    return label + ('' if row['supported'] else '  [unknown fixture]')


def build_catalog(data_root=DEFAULT_DATA, prediction_roots=None):
    """Use dataset split membership and export metadata, never sample ID guesses."""
    import h5py
    import numpy as np
    source_issues = {}
    with open_samples(Path(data_root)) as archive:
        teaching = sample_index(archive)
        for sample, member in teaching.items():
            try:
                with h5py.File(io.BytesIO(archive.read(member)), 'r') as handle:
                    for key in ('trajectory', 'joint_values', 'original_points'):
                        value = np.asarray(handle[key])
                        widths = (3, 6) if key == 'trajectory' else (6,)
                        if value.ndim != 2 or value.shape[1] not in widths or len(value) < 2:
                            raise ValueError(f'{key}: invalid array shape {value.shape}')
                        if not np.isfinite(value).all():
                            raise ValueError(f'{key}: source data contains NaN/Inf')
            except (OSError, ValueError, KeyError) as exc:
                source_issues[sample] = str(exc)
    membership = {}
    for split, directory in SPLITS.items():
        for path in (Path(data_root)/'2.데이터(NIA)'/directory).rglob('*.json'):
            if path.stem in teaching:
                if path.stem in membership and membership[path.stem] != split:
                    raise ValueError(f'Sample appears in both Train and Valid: {path.stem}')
                membership[path.stem] = split
    for sample in teaching:
        membership.setdefault(sample, 'unassigned')
    if prediction_roots is None:
        prediction_roots = discover_prediction_roots()
    exports = {}
    metrics = {}
    warnings = []
    for root in prediction_roots:
        for path in sorted(Path(root).glob('*/metadata.json')):
            try:
                meta = json.loads(path.read_text(encoding='utf-8'))
                sample = meta['episode_id']
                split = normalize_split(meta.get('split'))
                if sample not in membership:
                    continue
                if split != membership[sample]:
                    warnings.append(f'{path.parent.name}: export split does not match dataset')
                    continue
                if not (path.parent/'trajectory.npz').is_file():
                    warnings.append(f'{path.parent.name}: trajectory.npz missing')
                    continue
                exports.setdefault(sample, []).append(Path(root).resolve())
                metrics.setdefault(sample, {})[Path(root).resolve()] = error_label(meta, path.parent/'trajectory.npz')
            except (OSError, ValueError, KeyError) as exc:
                warnings.append(f'{path}: {exc}')
    rows = [dict(sample=sample, split=split,
                 supported=fixture_supported(sample), source_issue=source_issues.get(sample),
                 prediction_roots=exports.get(sample, []), prediction_metrics=metrics.get(sample, {}))
            for sample, split in sorted(membership.items())]
    return rows, warnings


def select_rows(rows, split, mode, query=''):
    return sorted((r for r in rows if r['split'] == split
                   and (mode == 'gt' or r['prediction_roots'])
                   and query.casefold() in r['sample'].casefold()),
                  key=lambda r: (not r['supported'], r['sample']))


def preparation_command(row, mode, duration, queue_dir=DEFAULT_QUEUE, prediction_root=None, layout="stp"):
    command = [sys.executable, str(ROOT/'run_welding_sample.py'), '--send',
               '--sample', row['sample'], '--duration-sec', str(duration),
               '--queue-dir', str(queue_dir), '--dataset-split', row['split'], '--layout', layout]
    if mode == 'predict':
        if prediction_root not in row['prediction_roots']:
            raise ValueError('No matching prediction export selected')
        command += ['--prediction', '--prediction-root', str(prediction_root)]
    return command


def server_running(queue_dir=DEFAULT_QUEUE):
    try:
        with (Path(queue_dir)/'server.lock').open('r') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(handle, fcntl.LOCK_UN)
    except OSError:
        pass
    return False


def queue_records(queue_dir=DEFAULT_QUEUE):
    records = {}
    for directory in ('pending', 'active', 'results'):
        for path in (Path(queue_dir)/directory).glob('*.json'):
            try:
                value = json.loads(path.read_text())
                value.setdefault('state', 'queued' if directory == 'pending' else 'running')
                records[path.stem] = value
            except (OSError, ValueError):
                continue
    return [records[key] for key in sorted(records, reverse=True)]


class Menu:
    def __init__(self, screen):
        self.screen = screen
        self.duration = 15
        self.layout = "stp"
        self.manual_prediction_roots = []
        self.prediction_roots = discover_prediction_roots()
        self.rows = []
        self.warnings = []
        self.screen.keypad(True)
        self.screen.timeout(200)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def line(self, y, text, selected=False):
        height, width = self.screen.getmaxyx()
        if y >= height-1:
            return
        # Most menu labels are ASCII; curses still supports Unicode sample paths.
        try:
            self.screen.addnstr(y, 1, str(text).replace('\n', ' '), max(0, width-3),
                                curses.A_REVERSE if selected else curses.A_NORMAL)
        except curses.error:
            pass

    def header(self, title):
        self.screen.erase()
        self.line(0, 'WELDING DEMO  |  '+title)
        self.line(1, f'Simulator: {"RUNNING" if server_running() else "OFFLINE (requests will wait)"}'
                     f'  |  Duration: {self.duration}s  |  Layout: {self.layout}')

    def choose(self, title, labels, searchable=False, footer=''):
        index = 0
        query = ''
        while True:
            self.header(title)
            self.line(3, 'Up/Down: select | Enter: open | Esc/Backspace: back | PgUp/PgDn: page')
            self.line(4, ('Type to filter: '+query) if searchable else footer)
            visible = [(i, label) for i, label in enumerate(labels)
                       if not searchable or query.casefold() in label.casefold()]
            index = min(index, max(0, len(visible)-1))
            page = max(1, self.screen.getmaxyx()[0]-9)
            offset = (index//page)*page
            for y, (_, label) in enumerate(visible[offset:offset+page], 6):
                self.line(y, ('> ' if y-6+offset == index else '  ')+label, y-6+offset == index)
            if not visible:
                self.line(6, '(No matching samples)')
            self.line(self.screen.getmaxyx()[0]-2, f'{index+1 if visible else 0}/{len(visible)}')
            self.screen.refresh()
            key = self.read_key()
            if key in (27, '\x1b'):
                return None
            if key in (curses.KEY_BACKSPACE, '\x7f', '\b'):
                if searchable and query:
                    query = query[:-1]; index = 0
                else:
                    return None
            elif key in (curses.KEY_UP, curses.KEY_DOWN):
                index = (index + (-1 if key == curses.KEY_UP else 1)) % max(1, len(visible))
            elif key in (curses.KEY_PPAGE, curses.KEY_NPAGE):
                index = min(max(0, index + (-page if key == curses.KEY_PPAGE else page)), max(0, len(visible)-1))
            elif key == curses.KEY_HOME:
                index = 0
            elif key == curses.KEY_END:
                index = max(0, len(visible)-1)
            elif key in ('\n', '\r', curses.KEY_ENTER) and visible:
                return visible[index][0]
            elif searchable and isinstance(key, str) and key.isprintable():
                query += key; index = 0

    def read_key(self):
        try:
            return self.screen.get_wch()
        except curses.error:
            return None

    def message(self, title, text):
        # Scrollable, including full preparation/IK errors.
        offset = 0
        while True:
            self.header(title)
            width = max(10, self.screen.getmaxyx()[1]-4)
            lines = [part for line in text.splitlines()
                     for part in (textwrap.wrap(line, width) or [''])]
            size = max(1, self.screen.getmaxyx()[0]-7)
            offset = min(offset, max(0, len(lines)-size))
            self.line(3, 'Enter/Esc: back | Up/Down: scroll')
            for y, line in enumerate(lines[offset:offset+size], 5):
                self.line(y, line)
            self.screen.refresh()
            key = self.read_key()
            if key in ('\n', '\r', '\x1b', curses.KEY_ENTER):
                return
            if key == curses.KEY_DOWN:
                offset = min(offset+1, max(0, len(lines)-size))
            elif key == curses.KEY_UP:
                offset = max(0, offset-1)

    def refresh(self):
        self.header('Scanning dataset and prediction exports...')
        self.screen.refresh()
        self.prediction_roots = sorted(set(discover_prediction_roots()) | set(self.manual_prediction_roots))
        self.rows, self.warnings = build_catalog(prediction_roots=self.prediction_roots)

    def play(self, row, mode, prediction_root=None):
        if row.get('source_issue'):
            self.message('Invalid source H5', f'{row["sample"]}: {row["source_issue"]}\n'
                         'The fixture is supported, but source data must be repaired before playback.')
            return
        if not row['supported']:
            self.message('Unsupported workpiece',
                         f'{row["sample"]}: unknown joint/material code (expected B/C/E/L/T and PP/PR/PS/RR/RS/SS).\n'
                         'This is a simulator geometry limitation, not a model failure.')
            return
        if mode == 'predict' and prediction_root is None:
            roots = row['prediction_roots']
            choice = 0 if len(roots) == 1 else self.choose('Prediction export', [str(p) for p in roots])
            if choice is None:
                return
            prediction_root = roots[choice]
        command = preparation_command(row, mode, self.duration, prediction_root=prediction_root, layout=self.layout)
        # Keep child stdout/stderr away from curses and remain responsive during IK.
        with tempfile.TemporaryFile(mode='w+t', encoding='utf-8') as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
            try:
                while process.poll() is None:
                    self.header(f'Preparing {row["sample"]} / {"GT" if mode == "gt" else "MODEL PREDICT"}')
                    self.line(4, 'Solving trajectory, then submitting to the simulator...')
                    self.line(6, 'Esc: cancel preparation (an already submitted request remains queued)')
                    self.screen.refresh()
                    if self.read_key() == '\x1b':
                        process.terminate()
                        break
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()
            finally:
                if process.poll() is None:
                    process.terminate(); process.wait()
            log.seek(0)
            output = log.read()
        title = 'QUEUED - playback not yet confirmed' if process.returncode == 0 else 'Preparation failed / cancelled'
        self.message(title, output + '\n\nOpen Queue / status to check running, done, or failed.')

    def samples(self, split, mode):
        rows = select_rows(self.rows, split, mode)
        if not rows:
            self.message('No samples', f'No {split.upper()} {mode.upper()} samples found.\n'
                         'Prediction playback requires an exported trajectory.npz and metadata.json '
                         'with a matching episode_id and split.\n'
                         'Use Add prediction folder, then Refresh. GT is never substituted for a prediction.')
            return
        prediction_root = None
        if mode == 'predict':
            roots = sorted({root for row in rows for root in row['prediction_roots']})
            families = sorted({prediction_family(root) for root in roots})
            family_choice = self.choose('SELECT MODEL', families)
            if family_choice is None:
                return
            roots = [root for root in roots if prediction_family(root) == families[family_choice]]
            choice = 0 if len(roots) == 1 else self.choose(
                'SELECT MODEL EXPORT', [prediction_export_label(root) for root in roots],
                footer='Select model first: sample errors belong to this export.')
            if choice is None:
                return
            prediction_root = roots[choice]
            rows = [row for row in rows if prediction_root in row['prediction_roots']]
        labels = [sample_label(row, mode, prediction_root) for row in rows]
        while True:
            title = f'{split.upper()} / GT' if mode == 'gt' else f'{split.upper()} / {prediction_export_label(prediction_root)} / ADE=mean, FDE=end'
            chosen = self.choose(title, labels, True)
            if chosen is None:
                return
            self.play(rows[chosen], mode, prediction_root)

    def status(self):
        while True:
            records = queue_records()
            labels = [f'{r.get("state", "?"):12} {r.get("dataset_split", "")} '
                      f'{r.get("playback_mode", "")} {r.get("sample", "")}  {r["id"]}' for r in records]
            labels = ['Refresh status'] + labels
            choice = self.choose('QUEUE / STATUS', labels, footer='Select request for details. Refresh to update states.')
            if choice is None:
                return
            if choice:
                self.message('Request details', json.dumps(records[choice-1], ensure_ascii=False, indent=2))

    def add_folder(self):
        self.header('Add prediction export folder')
        self.line(4, 'Path to folder containing episode subfolders (blank: cancel):')
        self.screen.refresh()
        curses.echo()
        self.screen.timeout(-1)
        try:
            value = self.screen.getstr(6, 1, 1000).decode('utf-8').strip()
        finally:
            curses.noecho()
            self.screen.timeout(200)
        if value:
            path = Path(value).expanduser().resolve()
            if not path.is_dir():
                self.message('Folder not found', str(path))
                return
            if path not in self.manual_prediction_roots:
                self.manual_prediction_roots.append(path)
            self.refresh()

    def run(self):
        self.refresh()
        while True:
            labels = ['Train', 'Valid', 'Unassigned (H5 only)', 'Queue / status', f'Playback duration ({self.duration}s)',
                      'Add prediction folder', 'Refresh dataset', 'Catalog warnings', f'Layout ({self.layout})', 'Quit']
            choice = self.choose('SELECT DATASET', labels)
            if choice is None or choice == 9:
                return
            if choice < 3:
                split = ('train', 'valid', 'unassigned')[choice]
                modes = ['GT', 'Model Predict']
                counts = [len(select_rows(self.rows, split, mode)) for mode in ('gt', 'predict')]
                mode = self.choose(split.upper(), [f'{name}  ({count} samples)' for name, count in zip(modes, counts)])
                if mode is not None:
                    self.samples(split, ('gt', 'predict')[mode])
            elif choice == 3:
                self.status()
            elif choice == 4:
                values = [5, 10, 15, 30, 60]
                index = self.choose('PLAYBACK DURATION', [f'{value} seconds' for value in values])
                if index is not None:
                    self.duration = values[index]
            elif choice == 5:
                self.add_folder()
            elif choice == 6:
                self.refresh()
            elif choice == 8:
                selected = self.choose('ENVIRONMENT LAYOUT', ['Legacy: existing fixture', 'STP reference: measured supports (approx.)'])
                if selected is not None:
                    self.layout = ('legacy', 'stp')[selected]
            elif choice == 7:
                self.message('Catalog warnings', '\n'.join(self.warnings) or 'None')


def main():
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise RuntimeError('Interactive menu needs a terminal. Existing --sample/--send CLI options remain available.')
    try:
        curses.wrapper(lambda screen: Menu(screen).run())
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
