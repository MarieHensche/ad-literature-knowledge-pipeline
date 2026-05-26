from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ad_lit_pipeline.topics.contract import (
    load_topic_contract,
    tagging_config_from_contract,
    validate_topic_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )


def test_early_detection_topic_contract_loads() -> None:
    contract = load_topic_contract(ROOT / "configs/topics/early_detection_ad.yaml")

    assert contract["topic_id"] == "early_detection_ad"
    assert "main_topic_category" in contract["tagging"]["categories"]
    assert "research_target" in contract["tagging"]["categories"]
    assert contract["collection"]["allowed_providers"] == ["openalex"]
    assert contract["collection"]["exclude_openalex_review_type"] is True
    assert contract["rule_based_screening"]["exclude_wins"] is True
    assert "mild cognitive impairment" in contract["rule_based_screening"][
        "include_terms"
    ]


def test_non_ad_topic_contract_loads() -> None:
    contract = load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml")

    assert contract["topic_id"] == "ai_in_education"
    assert "main_topic_category" in contract["tagging"]["categories"]
    assert "research_target" in contract["tagging"]["categories"]


def test_topic_contract_converts_to_legacy_tagging_config() -> None:
    contract = load_topic_contract(ROOT / "configs/topics/early_detection_ad.yaml")
    config = tagging_config_from_contract(contract)

    assert config["research_topic"]["title"].startswith("Early detection")
    assert len(config["categories"]) == 12
    assert "main_topic_category" in config["categories"]
    assert "research_target" in config["categories"]
    assert config["categories"]["review_status"]["required"] is True
    assert config["categories"]["review_status"]["values"] == [
        "ai_tagged",
        "human_reviewed",
        "needs_decision",
        "full_text_needed",
        "excluded_from_scope",
    ]


def test_normalize_tagging_config_accepts_topic_contract(tmp_path: Path) -> None:
    output = tmp_path / "normalized.json"

    run_script(
        "scripts/normalize_tagging_config.py",
        "--topic-contract",
        "configs/topics/early_detection_ad.yaml",
        "--output",
        str(output),
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["source_config"] == "configs/topics/early_detection_ad.yaml"
    assert payload["source_type"] == "topic_contract"
    assert payload["category_count"] == 12
    review_status = [
        category
        for category in payload["categories"]
        if category["category_id"] == "review_status"
    ][0]
    assert review_status["required"] is True


def test_topic_contract_requires_generic_mantis_categories() -> None:
    contract = load_topic_contract(ROOT / "configs/topics/early_detection_ad.yaml")
    del contract["tagging"]["categories"]["main_topic_category"]

    with pytest.raises(ValueError, match="main_topic_category"):
        validate_topic_contract(contract)
