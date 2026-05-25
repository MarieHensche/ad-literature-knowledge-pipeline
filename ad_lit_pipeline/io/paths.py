from __future__ import annotations

from pathlib import Path


def ensure_parent(path: Path) -> None:
    """Create a file path's parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)

