# the script that will call OpenAI and create
# This script will:
# 1. Read:
# data/processed/example_tagging_config_normalized.json
# 2. Send the research topic + categories/values to OpenAI.
# 3. Ask for fixed rules:
# single or multi
# required true/false
# fallback value
# reason
# 4. Save:
#data/processed/example_tagging_rules.json

#!/usr/bin/env python3
"""Generate fixed tagging rules from a normalized tagging config."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from openai import OpenAI


RULE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "rules": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category_id": {"type": "string"},
                    "selection": {"type": "string", "enum": ["single", "multi"]},
                    "required": {"type": "boolean"},
                    "fallback_value": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": [
                    "category_id",
                    "selection",
                    "required",
                    "fallback_value",
                    "reason",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["rules"],
    "additionalProperties": False,
}


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


def allowed_values_by_category(config: dict[str, object]) -> dict[str, set[str]]:
    categories = config.get("categories")
    if not isinstance(categories, list):
        raise ValueError("Normalized config must contain a categories list.")

    allowed = {}
    for category in categories:
        category_id = category["category_id"]
        values = category["allowed_values"]
        allowed[category_id] = {value["value"] for value in values}

    return allowed


def required_by_category(config: dict[str, object]) -> dict[str, bool]:
    return {
        category["category_id"]: bool(category.get("required", False))
        for category in config["categories"]
    }


def build_prompt(config: dict[str, object]) -> str:
    return f"""
You are preparing fixed tagging rules for a scientific literature knowledge-tagging pipeline.

The rules will be generated once, frozen, and then applied consistently to every paper.

Research topic:
{json.dumps(config["research_topic"], indent=2)}

Categories and allowed values:
{json.dumps(config["categories"], indent=2)}

For each category, decide:
- selection: "single" if exactly one value should usually be chosen, or "multi" if more than one value may be valid.
- required: true if the category should be filled for every included paper, otherwise false.
- fallback_value: one allowed value from that category to use when the paper is unclear or not enough information is available.

Rules:
- Return exactly one rule per category.
- Use only the provided category_id values.
- fallback_value must be one of the allowed values for that exact category.
- Never use "unclear" as fallback_value unless "unclear" is explicitly listed as an allowed value for that category.
- If "unclear" is allowed, prefer it as the fallback_value.
- If "mixed_or_unclear" is allowed and "unclear" is not allowed, use "mixed_or_unclear" as the fallback_value.
- If "not_reported" is allowed, use it when missing information is the likely issue.
- For knowledge_confidence, use "very_low" as the fallback_value.
- For review_status, use "needs_decision" as the fallback_value unless a better allowed value clearly applies.
- If a category is marked required in the input config, keep it required.
- Do not invent new categories or values.
""".strip()


def call_openai(config: dict[str, object], model: str) -> dict[str, object]:
    client = OpenAI()

    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "system",
                "content": "You generate stable ontology tagging rules as strict JSON.",
            },
            {
                "role": "user",
                "content": build_prompt(config),
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "tagging_rules",
                "strict": True,
                "schema": RULE_RESPONSE_SCHEMA,
            }
        },
    )

    return json.loads(response.output_text)


def validate_rules(config: dict[str, object], result: dict[str, object]) -> None:
    allowed = allowed_values_by_category(config)
    required_flags = required_by_category(config)

    rules = result.get("rules")
    if not isinstance(rules, list):
        raise ValueError("LLM response must contain a rules list.")

    seen = set()

    for rule in rules:
        category_id = rule.get("category_id")
        if category_id not in allowed:
            raise ValueError(f"Unknown category in rules: {category_id}")

        if category_id in seen:
            raise ValueError(f"Duplicate rule for category: {category_id}")
        seen.add(category_id)

        fallback_value = rule.get("fallback_value")
        if fallback_value not in allowed[category_id]:
            raise ValueError(
                f"Invalid fallback_value for {category_id}: {fallback_value}"
            )

        if required_flags[category_id] and not rule.get("required"):
            raise ValueError(f"Required category cannot be made optional: {category_id}")

    missing = set(allowed) - seen
    if missing:
        raise ValueError(f"Missing rules for categories: {', '.join(sorted(missing))}")


def write_output(
    output_path: Path,
    config_path: Path,
    model: str,
    result: dict[str, object],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "source_config": str(config_path),
        "model": model,
        "rules_count": len(result["rules"]),
        "rules": result["rules"],
    }

    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate fixed tagging rules.")
    parser.add_argument(
        "--config",
        default="data/processed/example_tagging_config_normalized.json",
        help="Normalized tagging config JSON.",
    )
    parser.add_argument(
        "--output",
        default="data/processed/example_tagging_rules.json",
        help="Output tagging rules JSON.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="OpenAI model. Defaults to OPENAI_MODEL or gpt-4o-mini.",
    )
    args = parser.parse_args()

    load_dotenv()

    model = args.model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    config_path = Path(args.config)
    output_path = Path(args.output)

    config = load_json(config_path)
    result = call_openai(config, model)
    validate_rules(config, result)
    write_output(output_path, config_path, model, result)

    print("Generated fixed tagging rules")
    print(f"Rules: {len(result['rules'])}")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()