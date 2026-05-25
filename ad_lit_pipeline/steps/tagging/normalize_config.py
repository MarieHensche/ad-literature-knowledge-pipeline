from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.topics.contract import (
    load_topic_contract,
    tagging_config_from_contract,
)


STEP = StepSpec(
    name="normalize_tagging_config",
    inputs=["tagging_config_yaml"],
    outputs=["tagging_config_normalized_json"],
    uses_llm=False,
    description="Normalize topic and category config into AI-ready JSON.",
)


def clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_values(values: object) -> list[dict[str, str]]:
    if not isinstance(values, list):
        raise ValueError("Category values must be a list.")

    normalized = []
    for value in values:
        normalized.append(
            {
                "value": clean_text(value),
                "label": clean_text(value),
            }
        )

    return normalized


def normalize_category(category_id: str, category: object) -> dict[str, object]:
    if not isinstance(category, dict):
        raise ValueError(f"Category must be a dictionary: {category_id}")

    values = normalize_values(category.get("values", []))

    if not values:
        raise ValueError(f"Category has no values: {category_id}")

    return {
        "category_id": clean_text(category_id),
        "label": clean_text(category.get("label") or category_id.replace("_", " ")),
        "description": clean_text(category.get("description")),
        "required": bool(category.get("required", False)),
        "allowed_values": values,
    }


def load_config(config_path: Path) -> dict[str, object]:
    with config_path.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    if not isinstance(config, dict):
        raise ValueError("Tagging config must be a YAML dictionary.")

    if not isinstance(config.get("research_topic"), dict):
        raise ValueError("Tagging config must contain research_topic.")

    if not isinstance(config.get("categories"), dict):
        raise ValueError("Tagging config must contain categories.")

    return config


def normalize_config(config: dict[str, object]) -> dict[str, object]:
    topic = config["research_topic"]
    categories = config["categories"]

    normalized_topic = {
        "title": clean_text(topic.get("title")),
        "description": clean_text(topic.get("description")),
    }

    if not normalized_topic["title"]:
        raise ValueError("research_topic.title is required.")

    if not normalized_topic["description"]:
        raise ValueError("research_topic.description is required.")

    normalized_categories = [
        normalize_category(category_id, category)
        for category_id, category in categories.items()
    ]

    return {
        "research_topic": normalized_topic,
        "category_count": len(normalized_categories),
        "categories": normalized_categories,
    }


def write_output(
    output_path: Path,
    source_path: Path,
    normalized: dict[str, object],
    source_type: str = "tagging_config",
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "source_config": str(source_path),
        **normalized,
    }
    if source_type != "tagging_config":
        payload["source_type"] = source_type

    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_config_input(
    config_path: Path | None,
    topic_contract_path: Path | None,
) -> tuple[dict[str, object], Path, str]:
    if topic_contract_path is not None:
        contract = load_topic_contract(topic_contract_path)
        return (
            tagging_config_from_contract(contract),
            topic_contract_path,
            "topic_contract",
        )

    if config_path is None:
        raise ValueError("Provide either --config or --topic-contract.")

    return load_config(config_path), config_path, "tagging_config"


def run(
    output_path: Path,
    config_path: Path | None = None,
    topic_contract_path: Path | None = None,
) -> StepResult:
    config, source_path, source_type = load_config_input(config_path, topic_contract_path)
    normalized = normalize_config(config)
    write_output(output_path, source_path, normalized, source_type)
    return StepResult(
        step_name=STEP.name,
        inputs={source_type: source_path},
        outputs={"tagging_config_normalized_json": output_path},
        row_counts={"categories": int(normalized["category_count"])},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize tagging config.")
    parser.add_argument(
        "--config",
        default="configs/early_detection_tagging_config.yaml",
        help="Input YAML tagging config.",
    )
    parser.add_argument(
        "--topic-contract",
        default=None,
        help="Input YAML topic contract. Overrides --config when provided.",
    )
    parser.add_argument(
        "--output",
        default="data/processed/example_tagging_config_normalized.json",
        help="Normalized tagging config output JSON.",
    )
    args = parser.parse_args()

    config_path = Path(args.config) if args.config else None
    topic_contract_path = Path(args.topic_contract) if args.topic_contract else None
    output_path = Path(args.output)

    result = run(output_path, config_path, topic_contract_path)

    print("Normalized tagging config")
    print(f"Categories: {result.row_counts['categories']}")
    print(f"Wrote {output_path}")
