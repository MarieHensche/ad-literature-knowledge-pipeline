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
    dependencies: tuple[str, ...] = ()
    capabilities: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("StepSpec name must be non-empty.")
        dependencies = tuple(self.dependencies)
        capabilities = frozenset(self.capabilities)
        if self.name in dependencies:
            raise ValueError(f"Step {self.name!r} cannot depend on itself.")
        if len(dependencies) != len(set(dependencies)):
            raise ValueError(f"Step {self.name!r} has duplicate dependencies.")
        if any(not item.strip() for item in dependencies):
            raise ValueError(f"Step {self.name!r} has an empty dependency name.")
        if any(not item.strip() for item in capabilities):
            raise ValueError(f"Step {self.name!r} has an empty capability name.")
        object.__setattr__(self, "dependencies", dependencies)
        object.__setattr__(self, "capabilities", capabilities)


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
