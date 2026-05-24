#!/usr/bin/env python3
"""Tag included papers with fixed knowledge tags using an LLM."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path

from openai import OpenAI


def load_dotenv(env_path: Path = Path(".env")) -> None:
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")

    return data


def read_included_papers(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    return [row for row in rows if row.get("scope_decision") == "include"]


def categories_from_config(config: dict[str, object]) -> list[dict[str, object]]:
    categories = config.get("categories")
    if not isinstance(categories, list):
        raise ValueError("Normalized tagging config must contain categories list.")
    return categories


def rules_by_category(rules: dict[str, object]) -> dict[str, dict[str, object]]:
    rule_list = rules.get("rules")
    if not isinstance(rule_list, list):
        raise ValueError("Tagging rules must contain rules list.")
    return {rule["category_id"]: rule for rule in rule_list}


def allowed_values_by_category(config: dict[str, object]) -> dict[str, set[str]]:
    allowed = {}
    for category in categories_from_config(config):
        category_id = category["category_id"]
        allowed[category_id] = {
            value["value"] for value in category.get("allowed_values", [])
        }
    return allowed


def build_response_schema(config: dict[str, object]) -> dict[str, object]:
    properties = {
        "paper_id": {"type": "string"},
        "main_knowledge_claim": {"type": "string"},
    }
    required = ["paper_id", "main_knowledge_claim"]

    for category in categories_from_config(config):
        category_id = category["category_id"]
        properties[category_id] = {
            "type": "array",
            "items": {"type": "string"},
        }
        required.append(category_id)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def paper_text(paper: dict[str, str]) -> dict[str, str]:
    return {
        "paper_id": paper.get("paper_id", ""),
        "title": paper.get("title", ""),
        "year": paper.get("year", ""),
        "doi": paper.get("doi", ""),
        "abstract": paper.get("abstract", ""),
        "authors": paper.get("authors", ""),
        "venue": paper.get("venue", ""),
        "source": paper.get("source", ""),
        "full_text_path": paper.get("full_text_path", ""),
    }


def build_prompt(
    paper: dict[str, str],
    config: dict[str, object],
    rules: dict[str, object],
) -> str:
    return f"""
You are tagging one scientific paper for a knowledge-map pipeline.

Research topic:
{json.dumps(config["research_topic"], indent=2)}

Paper:
{json.dumps(paper_text(paper), indent=2)}

Allowed categories and values:
{json.dumps(config["categories"], indent=2)}

Fixed tagging rules:
{json.dumps(rules["rules"], indent=2)}

Task:
Assign the best-fitting knowledge tags for this paper.

Rules:
- Use only the allowed category IDs.
- Use only allowed values listed for each category.
- Return every category as an array of selected values.
- For single-selection categories, return exactly one value in the array.
- For multi-selection categories, return one or more values if relevant.
- If the paper does not provide enough information, use the category fallback value from the fixed rules.
- Do not invent new values.
- main_knowledge_claim should be one concise sentence describing what the paper contributes to the research topic.
- Set review_status to ["ai_tagged"] unless the paper clearly needs a human decision.
""".strip()


def call_openai(
    paper: dict[str, str],
    config: dict[str, object],
    rules: dict[str, object],
    model: str,
) -> dict[str, object]:
    client = OpenAI()
    response_schema = build_response_schema(config)

    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "system",
                "content": "You tag scientific papers using fixed ontology rules as strict JSON.",
            },
            {
                "role": "user",
                "content": build_prompt(paper, config, rules),
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "paper_tags",
                "strict": True,
                "schema": response_schema,
            }
        },
    )

    return json.loads(response.output_text)


def validate_tagged_row(
    tagged: dict[str, object],
    config: dict[str, object],
    rules: dict[str, object],
) -> None:
    allowed = allowed_values_by_category(config)
    rule_map = rules_by_category(rules)

    for category_id, allowed_values in allowed.items():
        values = tagged.get(category_id)

        if not isinstance(values, list):
            raise ValueError(f"{category_id} must be a list.")

        if not values:
            raise ValueError(f"{category_id} has no selected value.")

        invalid = [value for value in values if value not in allowed_values]
        if invalid:
            raise ValueError(f"{category_id} has invalid value(s): {invalid}")

        if rule_map[category_id]["selection"] == "single" and len(values) != 1:
            fallback_value = rule_map[category_id].get("fallback_value")
            if len(values) > 1:
                tagged[category_id] = [values[0]]
            elif fallback_value in allowed_values:
                tagged[category_id] = [fallback_value]
            else:
                raise ValueError(f"{category_id} must have exactly one selected value.")


def output_columns(config: dict[str, object]) -> list[str]:
    columns = [
        "paper_id",
        "title",
        "year",
        "doi",
        "main_knowledge_claim",
    ]

    columns.extend(category["category_id"] for category in categories_from_config(config))

    return columns


def flatten_tagged_row(
    paper: dict[str, str],
    tagged: dict[str, object],
    config: dict[str, object],
) -> dict[str, str]:
    row = {
        "paper_id": paper.get("paper_id", ""),
        "title": paper.get("title", ""),
        "year": paper.get("year", ""),
        "doi": paper.get("doi", ""),
        "main_knowledge_claim": str(tagged.get("main_knowledge_claim", "")),
    }

    for category in categories_from_config(config):
        category_id = category["category_id"]
        row[category_id] = "; ".join(tagged[category_id])

    return row


def write_rows(output_path: Path, rows: list[dict[str, str]], config: dict[str, object]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=output_columns(config))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Tag papers with an LLM.")
    parser.add_argument(
        "--papers",
        default="data/processed/example_scope_screened.csv",
        help="Scope-screened paper CSV.",
    )
    parser.add_argument(
        "--config",
        default="data/processed/example_tagging_config_normalized.json",
        help="Normalized tagging config JSON.",
    )
    parser.add_argument(
        "--rules",
        default="data/processed/example_tagging_rules.json",
        help="Fixed tagging rules JSON.",
    )
    parser.add_argument(
        "--output",
        default="data/processed/example_extraction_filled.csv",
        help="Tagged extraction output CSV.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="OpenAI model. Defaults to OPENAI_MODEL or gpt-4o-mini.",
    )
    args = parser.parse_args()

    load_dotenv()

    model = args.model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    papers_path = Path(args.papers)
    config_path = Path(args.config)
    rules_path = Path(args.rules)
    output_path = Path(args.output)

    papers = read_included_papers(papers_path)
    config = load_json(config_path)
    rules = load_json(rules_path)

    rows = []
    for index, paper in enumerate(papers, start=1):
        print(f"Tagging paper {index}/{len(papers)}: {paper.get('paper_id')}")
        tagged = call_openai(paper, config, rules, model)
        validate_tagged_row(tagged, config, rules)
        rows.append(flatten_tagged_row(paper, tagged, config))

    write_rows(output_path, rows, config)

    print(f"Tagged papers: {len(rows)}")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()