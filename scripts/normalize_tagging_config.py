#!/usr/bin/env python3
"""Normalize a tagging config into AI-ready topic and category instructions."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml


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


def write_output(output_path: Path, config_path: Path, normalized: dict[str, object]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "source_config": str(config_path),
        **normalized,
    }

    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize tagging config.")
    parser.add_argument(
        "--config",
        default="configs/early_detection_tagging_config.yaml",
        help="Input YAML tagging config.",
    )
    parser.add_argument(
        "--output",
        default="data/processed/example_tagging_config_normalized.json",
        help="Normalized tagging config output JSON.",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    output_path = Path(args.output)

    config = load_config(config_path)
    normalized = normalize_config(config)
    write_output(output_path, config_path, normalized)

    print("Normalized tagging config")
    print(f"Categories: {normalized['category_count']}")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()