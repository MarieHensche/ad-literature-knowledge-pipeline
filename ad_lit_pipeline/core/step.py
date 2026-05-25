from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StepSpec:
    """Static metadata describing one pipeline step."""

    name: str
    inputs: list[str]
    outputs: list[str]
    uses_llm: bool = False
    description: str = ""


@dataclass
class StepResult:
    """Result metadata returned after a pipeline step runs."""

    step_name: str
    inputs: dict[str, Path] = field(default_factory=dict)
    outputs: dict[str, Path] = field(default_factory=dict)
    row_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    trace_paths: list[Path] = field(default_factory=list)
    elapsed_seconds: float | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        """Return whether the step completed without an error."""
        return self.error is None

