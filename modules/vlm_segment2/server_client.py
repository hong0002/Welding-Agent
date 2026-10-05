#!/usr/bin/env python3
"""SSH를 이용한 임베딩 서버 연결·준비·파일 전송 도구."""

from __future__ import annotations

import argparse
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = PROJECT_DIR / "config" / "config.yaml"


@dataclass(frozen=True)
class ServerConfig:
    ssh_alias: str | None
    hostname: str
    port: int
    user: str
    identity_file: Path
    remote_root: PurePosixPath

    @property
    def destination(self) -> str:
        return self.ssh_alias or f"{self.user}@{self.hostname}"

    def ssh_command(self) -> list[str]:
        if self.ssh_alias:
            return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", self.ssh_alias]
        return [
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            "-p", str(self.port), "-i", str(self.identity_file),
            f"{self.user}@{self.hostname}",
        ]

    def scp_command(self) -> list[str]:
        if self.ssh_alias:
            return ["scp", "-q"]
        return [
            "scp", "-q", "-P", str(self.port), "-i", str(self.identity_file),
        ]


def load_server_config(path: Path) -> ServerConfig:
    if not path.exists():
        raise SystemExit(f"설정 파일이 없습니다: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = data.get("server")
    if not isinstance(raw, dict):
        raise SystemExit("config.yaml의 server 항목은 key-value 형식이어야 합니다.")

    required = ("hostname", "port", "user", "identity_file", "remote_root")
    missing = [key for key in required if not raw.get(key)]
    if missing:
        raise SystemExit(f"server 설정 누락: {', '.join(missing)}")

    identity_file = Path(str(raw["identity_file"])).expanduser()
    if not identity_file.is_file():
        raise SystemExit(f"SSH 개인키를 찾을 수 없습니다: {identity_file}")
    key_mode = identity_file.stat().st_mode & 0o777
    if key_mode & 0o077:
        raise SystemExit(
            f"SSH 개인키 권한이 너무 넓습니다({key_mode:o}). `chmod 600 {identity_file}`를 실행하세요."
        )

    return ServerConfig(
        ssh_alias=str(raw.get("ssh_alias")) if raw.get("ssh_alias") else None,
        hostname=str(raw["hostname"]),
        port=int(raw["port"]),
        user=str(raw["user"]),
        identity_file=identity_file,
        remote_root=PurePosixPath(str(raw["remote_root"])),
    )


def run_checked(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, text=True)


def remote_run(server: ServerConfig, command: str) -> None:
    run_checked([*server.ssh_command(), command])


def check(server: ServerConfig) -> None:
    command = (
        "printf 'status=ok\\n'; "
        "printf 'host='; hostname; "
        "printf 'user='; id -un; "
        "printf 'home='; printf '%s\\n' \"$HOME\"; "
        "printf 'python='; python3 --version 2>&1"
    )
    remote_run(server, command)
    print(f"[OK] SSH 연결: {server.destination}")


def prepare_remote(server: ServerConfig) -> None:
    root = shlex.quote(str(server.remote_root))
    command = (
        f"mkdir -p {root}/incoming {root}/embeddings {root}/index {root}/logs && "
        f"printf 'remote_root=%s\\n' {root} && "
        f"find {root} -maxdepth 1 -mindepth 1 -type d -printf '%f\\n' | sort"
    )
    remote_run(server, command)
    print(f"[OK] 서버 작업 폴더 준비 완료: {server.remote_root}")


def upload(server: ServerConfig, source: Path) -> None:
    source = source.expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"전송할 파일이 없습니다: {source}")
    allowed = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".json"}
    if source.suffix.lower() not in allowed:
        raise SystemExit(f"지원하지 않는 파일 형식입니다: {source.suffix}")

    incoming = server.remote_root / "incoming"
    # 업로드가 서버 폴더를 암묵적으로 만들지 않게 한다. 폴더 준비는 prepare로 명시한다.
    try:
        remote_run(server, f"test -d {shlex.quote(str(incoming))}")
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            f"서버 업로드 폴더가 없습니다: {incoming}\n"
            "먼저 `python server_client.py prepare`를 실행하세요."
        ) from exc
    target = f"{server.destination}:{shlex.quote(str(incoming / source.name))}"
    run_checked([*server.scp_command(), str(source), target])
    print(f"[OK] 업로드: {source.name} -> {incoming}")


def main() -> None:
    parser = argparse.ArgumentParser(description="VLM 임베딩 서버 SSH 클라이언트")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check", help="SSH 연결과 서버 기본 환경 확인")
    subparsers.add_parser("prepare", help="서버 작업 폴더 생성 및 확인")
    subparsers.add_parser("init", help="prepare의 이전 명령 이름")
    upload_parser = subparsers.add_parser("upload", help="이미지 또는 JSON 한 개 전송")
    upload_parser.add_argument("file", type=Path)
    args = parser.parse_args()

    server = load_server_config(args.config.expanduser().resolve())
    try:
        if args.command == "check":
            check(server)
        elif args.command in {"prepare", "init"}:
            prepare_remote(server)
        elif args.command == "upload":
            upload(server, args.file)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"서버 명령 실패(exit={exc.returncode})") from exc


if __name__ == "__main__":
    main()
