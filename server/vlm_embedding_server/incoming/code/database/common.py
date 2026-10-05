from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path


CAMERAS = ("B", "F", "L", "R", "S1", "S2", "S3", "S4", "T")
IMAGE_RE = re.compile(r"^(?P<sample>.+)_(?P<camera>B|F|L|R|S1|S2|S3|S4|T)_Color$")
SAMPLE_RE = re.compile(
    r"^(?P<joint_type>[A-Z]+)_(?P<material_pair>[A-Z]+)_(?P<thickness>\d+|M)_(?P<number>\d+)$"
)


def relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def parse_image_name(path: Path) -> tuple[str, str]:
    match = IMAGE_RE.fullmatch(path.stem)
    if not match:
        raise ValueError(f"카메라 파일명 형식이 아닙니다: {path.name}")
    return match.group("sample"), match.group("camera")


def parse_sample_metadata(sample_id: str) -> tuple[str | None, str | None, int | None, str]:
    match = SAMPLE_RE.fullmatch(sample_id)
    if not match:
        return None, None, None, sample_id
    thickness_text = match.group("thickness")
    thickness = int(thickness_text) if thickness_text.isdigit() else None
    return (
        match.group("joint_type"),
        match.group("material_pair"),
        thickness,
        match.group("number"),
    )


def load_records(manifest_path: Path, *, valid_only: bool = True) -> list[dict]:
    records: list[dict] = []
    with manifest_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"manifest {line_number}번째 줄이 잘못되었습니다") from exc
            if not valid_only or record.get("record_status") == "valid":
                records.append(record)
    return records


def open_metadata(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def resolve_db_path(db_root: Path, stored_path: str) -> Path:
    return (db_root / stored_path).resolve()

