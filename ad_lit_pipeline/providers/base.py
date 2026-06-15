from __future__ import annotations

from typing import Any, Protocol


class CandidateProvider(Protocol):
    """Interface for external candidate-paper providers."""

    name: str
    max_per_page: int

    def validate_plan(self, plan: dict[str, Any]) -> None:
        """Validate that a search plan can be executed by this provider."""

    def fetch_candidates(
        self,
        plan: dict[str, Any],
        max_results: int,
        per_page: int,
        mailto: str | None,
        sleep_seconds: float,
    ) -> list[dict[str, Any]]:
        """Fetch candidates for a validated provider-specific plan."""
