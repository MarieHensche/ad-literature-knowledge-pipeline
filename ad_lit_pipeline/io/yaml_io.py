from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def read_yaml_object(path: Path) -> dict[str, Any]:
    """Read a YAML file and require a top-level mapping."""
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Expected YAML object: {path}")
    return data


def write_yaml_object(path: Path, payload: dict[str, Any]) -> None:
    """Write a YAML mapping with stable key order and a trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )
