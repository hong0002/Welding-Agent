from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalConfig:
    ssh_alias: str
    remote_root: str
    remote_python: str


def retrieve_actions(config: RetrievalConfig, payload: dict) -> dict:
    root = config.remote_root.rstrip("/")
    command = (
        f"cd {shlex.quote(root)} && "
        f"PYTHONPATH={shlex.quote(root + ':' + root + '/incoming/code')} "
        f"{shlex.quote(config.remote_python)} -m service.retrieve_action"
    )
    completed = subprocess.run(
        ["ssh", config.ssh_alias, command],
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=False,
    )
    result = None
    for line in reversed(completed.stdout.splitlines()):
        try:
            result = json.loads(line)
            break
        except json.JSONDecodeError:
            continue
    if completed.returncode != 0 or not isinstance(result, dict):
        detail = (result.get("error") if isinstance(result, dict) else None) or completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"서버 액션 검색 실패(exit={completed.returncode}): {detail}")
    if result.get("error"):
        raise RuntimeError(f"서버 액션 검색 실패: {result['error']}")
    sample_id = str(payload["sample_id"])
    if any(item.get("sample_id") == sample_id for item in result.get("results", [])):
        raise RuntimeError(f"검색 결과에 현재 샘플이 포함됐습니다: {sample_id}")
    return result
