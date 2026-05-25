from __future__ import annotations

from pathlib import Path
from typing import Any

from ad_lit_pipeline.topics.contract import load_topic_contract


def load(path: Path) -> dict[str, Any]:
    """Load a topic contract from disk."""
    return load_topic_contract(path)

