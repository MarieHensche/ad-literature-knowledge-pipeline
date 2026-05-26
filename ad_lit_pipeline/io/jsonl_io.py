from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_jsonl_objects(path: Path) -> list[dict[str, Any]]:
    """Read JSONL records and require every non-empty line to be an object."""
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"Expected JSON object in {path}:{line_number}")
            rows.append(row)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write dictionaries as JSONL records."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

