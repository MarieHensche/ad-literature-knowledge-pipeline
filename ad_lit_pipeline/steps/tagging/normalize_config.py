from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.topics.contract import (
    VALID_CATEGORY_SELECTIONS,
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


def normalize_applies_when(
    category_id: str,
    applies_when: object,
) -> dict[str, object] | None:
    if applies_when in (None, {}):
        return None

    if not isinstance(applies_when, dict):
        raise ValueError(f"applies_when must be a dictionary: {category_id}")

    parent_id = clean_text(applies_when.get("category_id"))
    values = applies_when.get("values")
    if not parent_id:
        raise ValueError(f"applies_when.category_id is required: {category_id}")
    if not isinstance(values, list) or not values:
        raise ValueError(f"applies_when.values must be a non-empty list: {category_id}")

    normalized_values = [clean_text(value) for value in values]
    if not all(normalized_values):
        raise ValueError(f"applies_when.values must contain strings: {category_id}")

    return {
        "category_id": parent_id,
        "values": normalized_values,
    }


def normalize_category(category_id: str, category: object) -> dict[str, object]:
    if not isinstance(category, dict):
        raise ValueError(f"Category must be a dictionary: {category_id}")

    values = normalize_values(category.get("values", []))

    if not values:
        raise ValueError(f"Category has no values: {category_id}")

    selection = clean_text(category.get("selection"))
    if selection and selection not in VALID_CATEGORY_SELECTIONS:
        allowed = ", ".join(sorted(VALID_CATEGORY_SELECTIONS))
        raise ValueError(
            f"Category selection must be one of {allowed}: {category_id}"
        )

    normalized: dict[str, object] = {
        "category_id": clean_text(category_id),
        "label": clean_text(category.get("label") or category_id.replace("_", " ")),
        "description": clean_text(category.get("description")),
        "required": bool(category.get("required", False)),
        "allowed_values": values,
    }

    if selection:
        normalized["selection"] = selection

    applies_when = normalize_applies_when(category_id, category.get("applies_when"))
    if applies_when is not None:
        normalized["applies_when"] = applies_when

    return normalized


def validate_normalized_dependencies(categories: list[dict[str, object]]) -> None:
    allowed_by_category = {
        str(category["category_id"]): {
            str(value["value"]) for value in category.get("allowed_values", [])
        }
        for category in categories
    }

    for category in categories:
        category_id = str(category["category_id"])
        applies_when = category.get("applies_when")
        if not isinstance(applies_when, dict):
            continue

        parent_id = str(applies_when["category_id"])
        if parent_id == category_id:
            raise ValueError(f"applies_when cannot reference itself: {category_id}")
        if parent_id not in allowed_by_category:
            raise ValueError(
                f"applies_when references unknown category for {category_id}: "
                f"{parent_id}"
            )

        invalid_values = [
            value
            for value in applies_when.get("values", [])
            if value not in allowed_by_category[parent_id]
        ]
        if invalid_values:
            raise ValueError(
                f"applies_when references invalid value(s) for {category_id}: "
                f"{invalid_values}"
            )


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
    if not isinstance(categories, dict):
        raise ValueError("Tagging config must contain categories.")

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
    validate_normalized_dependencies(normalized_categories)

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
        default=None,
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
