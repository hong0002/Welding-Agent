"""Local, atomic file queue shared by the command terminal and Isaac Sim."""
import json
import os
from pathlib import Path
import time
import uuid

DEFAULT_QUEUE = Path(__file__).resolve().parent / 'welding_commands'


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def submit(directory, solution, output, duration, sample, playback_mode=None, dataset_split=None, record_video=None, video_dir=None, camera_distance_scale=1.0):
    directory = Path(directory).resolve()
    request_id = f'{time.time_ns():020d}_{uuid.uuid4().hex[:8]}'
    request = dict(id=request_id, sample=sample, solution=str(Path(solution).resolve()),
                   output=str(Path(output).resolve()), duration_sec=duration, camera_distance_scale=camera_distance_scale)
    if playback_mode is not None:
        request['playback_mode'] = playback_mode
    if dataset_split is not None:
        request['dataset_split'] = dataset_split
    if record_video is not None:
        request['record_video'] = bool(record_video)
    if video_dir is not None:
        request['video_dir'] = str(Path(video_dir).expanduser().resolve())
    write_json(directory / 'pending' / f'{request_id}.json', request)
    return request_id


def process_next(directory, play):
    """Process one command; failed requests do not stop the server."""
    directory = Path(directory)
    pending = sorted((directory / 'pending').glob('*.json'))
    if not pending:
        return False
    source = pending[0]
    active = directory / 'active' / source.name
    active.parent.mkdir(parents=True, exist_ok=True)
    source.replace(active)
    result = dict(id=source.stem, state='running')
    result_path = directory / 'results' / source.name
    try:
        request = json.loads(active.read_text(encoding='utf-8'))
        result['sample'] = request['sample']
        for key in ('playback_mode', 'dataset_split', 'output', 'duration_sec'):
            if key in request:
                result[key] = request[key]
        write_json(result_path, result)
        play(request)
        result['state'] = 'done'
    except Exception as exc:
        result.update(state='failed', error=f'{type(exc).__name__}: {exc}')
        print(f'[COMMAND ERROR] {result["error"]}', flush=True)
    except BaseException:
        result.update(state='interrupted', error='Simulator stopped during playback')
        raise
    finally:
        write_json(result_path, result)
        active.unlink(missing_ok=True)
    return True


def print_status(directory):
    directory = Path(directory)
    for folder in ('pending', 'active', 'results'):
        for path in sorted((directory / folder).glob('*.json')):
            record = json.loads(path.read_text(encoding='utf-8'))
            print(f'{record["id"]} {record.get("sample", "")} '
                  f'{record.get("state", folder)} {record.get("error", "")}')
    print('pending=대기, running/active=실행 중, done=완료, failed=실패')


def wait_for_result(directory, request_id):
    """Wait for playback AND recording/save to finish, not a fixed duration."""
    result_path = Path(directory) / 'results' / f'{request_id}.json'
    last_state = None
    while True:
        record = json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() else {}
        state = record.get('state', 'pending')
        if state != last_state:
            print(f'[WAIT] {request_id}: {state}', flush=True)
            last_state = state
        if state in ('done', 'failed', 'interrupted'):
            if record.get('error'):
                print(f'[PLAYBACK ERROR] {record["error"]}', flush=True)
            return state == 'done'
        time.sleep(1)
