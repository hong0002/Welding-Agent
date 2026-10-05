"""Windows/UTF-8 launcher only. Prediction remains owned by native predict.py."""
import json
import os
from pathlib import Path
import runpy
import sys

PROJECT = Path(__file__).resolve().parents[2]


def main():
    sys.path.insert(0, str(PROJECT))
    from backend.services.environment import backend_env_values
    from backend.model_clients.native import sha256
    attempt = Path(sys.argv[1]).resolve()
    if not attempt.is_relative_to(PROJECT / '.cache/native-models/gpt2-trajectory'):
        raise ValueError('GPT2_ATTEMPT_INVALID')
    launch = json.loads((attempt / 'launch.json').read_text(encoding='utf-8'))
    repository = Path(launch['repository']).resolve()
    config = attempt / 'native_config.yaml'
    if (repository != (PROJECT.parent / 'vlm_final_gpt2').resolve() or
            sha256(config) != launch['config_sha256'] or
            any(sha256(repository / n) != h for n, h in launch['native_code'].items())):
        raise ValueError('GPT2_SOURCE_CHANGED')
    shared = Path(launch['shared_root']).resolve()
    if not (shared / 'vlm_project2/fewshot_examples.py').is_file():
        raise ValueError('GPT2_NATIVE_RETRIEVAL_MISSING')
    if any(sha256(shared / n) != h for n, h in launch['shared_code'].items()):
        raise ValueError('GPT2_SOURCE_CHANGED')
    # Use the already audited Windows flock subset; never stub native retrieval.
    sys.path[:0] = [str(PROJECT / 'backend/simulator_compat'), str(repository), str(shared)]
    key = (backend_env_values().get('OPENAI_API_KEY') or '').strip()
    if not key:
        raise ValueError('GPT2_TOKEN_REQUIRED')
    os.environ['OPENAI_API_KEY'] = key
    os.environ['OPENAI_AGENTS_DISABLE_TRACING'] = '1'
    sys.argv = [str(repository / 'predict.py'), '--config', str(config),
                '--sample-id', launch['sample_id'], '--prediction-only']
    counts = {'model_stage_calls':0,'ssh_calls':0,'completed_stages':[]}
    def observe(frame,event,arg):
        # Function boundaries only: never record arguments, payloads or reasoning.
        if frame.f_code.co_filename == str(repository/'predict.py') and frame.f_code.co_name == 'call_stage':
            stage=frame.f_locals.get('stage')
            if stage in ('rough','corners'):
                if event=='call':
                    counts['model_stage_calls']+=1
                    print('\n[GPT2_STAGE] start='+stage,flush=True)
                elif event=='return' and isinstance(arg,dict):
                    counts['completed_stages'].append(stage)
                    print('\n[GPT2_STAGE] completed='+stage,flush=True)
    # Original CLI, two original stages, original exporter, no retry/fallback wrapper.
    from backend.model_clients.gpt2_retrieval_diagnostics import RetrievalDiagnostics
    diagnostics = RetrievalDiagnostics(shared, attempt/'retrieval_diagnostics.json', profile=observe)
    try:
        with diagnostics:
            runpy.run_path(str(repository / 'predict.py'), run_name='__main__')
    finally:
        counts['ssh_calls'] = diagnostics.report['ssh_calls']
        counts['ssh_exit_code'] = diagnostics.report.get('subprocess_exit_code')
        counts['ssh_reason_code'] = diagnostics.report.get('ssh_stderr_category')
        (attempt/'invocation_counts.json').write_text(json.dumps(counts),encoding='utf-8')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Never log raw exception messages/request bodies/prompts/keys.
        print('[GPT2_PROCESS_FAILED] exception=' + type(exc).__name__, flush=True)
        sys.exit(1)
