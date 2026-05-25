from __future__ import annotations

from typing import Any

from ad_lit_pipeline.topics.contract import validate_topic_contract


def validate(contract: dict[str, Any]) -> None:
    """Validate a topic contract mapping."""
    validate_topic_contract(contract)

