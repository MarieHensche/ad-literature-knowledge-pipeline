from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class RunContext:
    """Shared run settings for pipeline steps and orchestrators."""

    collection: str
    base_dir: Path = Path(".")
    run_id: str = field(default_factory=lambda: uuid4().hex)
    model: str | None = None
    topic_contract_path: Path | None = None
    tagging_config_path: Path | None = None
    trace_dir: Path | None = None

    def resolve(self, path: str | Path) -> Path:
        """Resolve a possibly relative path against the run base directory."""
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        return self.base_dir / candidate

