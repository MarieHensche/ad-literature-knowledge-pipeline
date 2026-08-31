from __future__ import annotations

from collections.abc import Mapping, Sequence
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


def candidate_provider_dates(
    candidates: Sequence[Mapping[str, Any]],
) -> dict[str, str | None]:
    """Summarize retrieval and provider-update dates retained on candidates."""
    retrieval_dates = sorted(
        {
            str(candidate.get("retrieval_date") or "").strip()
            for candidate in candidates
            if str(candidate.get("retrieval_date") or "").strip()
        }
    )
    provider_updated_dates = set()
    for candidate in candidates:
        raw_record = candidate.get("raw_record")
        if not isinstance(raw_record, Mapping):
            continue
        value = raw_record.get("updated_date") or raw_record.get("updated_at")
        if value is not None and str(value).strip():
            provider_updated_dates.add(str(value).strip())
    ordered_updates = sorted(provider_updated_dates)
    return {
        "retrieval_date_earliest": retrieval_dates[0] if retrieval_dates else None,
        "retrieval_date_latest": retrieval_dates[-1] if retrieval_dates else None,
        "provider_updated_at_earliest": (
            ordered_updates[0] if ordered_updates else None
        ),
        "provider_updated_at_latest": (
            ordered_updates[-1] if ordered_updates else None
        ),
    }
