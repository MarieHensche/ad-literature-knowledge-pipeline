from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.llm.client import JSONLLMClient, OpenAIResponsesClient
from ad_lit_pipeline.llm.schemas import RULE_RESPONSE_SCHEMA
from ad_lit_pipeline.llm.trace import LLMTraceWriter
from ad_lit_pipeline.prompts.render import render_generate_tagging_rules_prompt
from ad_lit_pipeline.topics.contract import VALID_CATEGORY_SELECTIONS, load_topic_contract


STEP = StepSpec(
    name="generate_tagging_rules",
    inputs=["tagging_config_json"],
    outputs=["tagging_rules_json"],
    uses_llm=True,
    description="Generate fixed tagging rules from a normalized tagging config.",
)

SYSTEM_MESSAGE = "You generate stable ontology tagging rules as strict JSON."


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


def selection_by_category(config: dict[str, object]) -> dict[str, str | None]:
    return {
        category["category_id"]: (
            str(category.get("selection"))
            if category.get("selection") in VALID_CATEGORY_SELECTIONS
            else None
        )
        for category in config["categories"]
    }


def applies_when_by_category(
    config: dict[str, object],
) -> dict[str, dict[str, object] | None]:
    return {
        str(category["category_id"]): (
            category.get("applies_when")
            if isinstance(category.get("applies_when"), dict)
            else None
        )
        for category in config["categories"]
    }


def ordered_category_ids(config: dict[str, object]) -> list[str]:
    categories = config.get("categories")
    if not isinstance(categories, list):
        raise ValueError("Normalized config must contain a categories list.")
    return [str(category["category_id"]) for category in categories]


def fallback_policy(topic_contract: dict[str, object] | None) -> dict[str, object]:
    if topic_contract is None:
        return {}
    tagging = topic_contract.get("tagging")
    if not isinstance(tagging, dict):
        return {}
    policy = tagging.get("fallback_policy")
    return policy if isinstance(policy, dict) else {}


def recommended_fallback_value(
    category_id: str,
    allowed_values: set[str],
    topic_contract: dict[str, object] | None = None,
) -> str:
    """Pick a deterministic legal fallback value for a category."""
    policy = fallback_policy(topic_contract)

    explicit = policy.get(category_id)
    if isinstance(explicit, str) and explicit in allowed_values:
        return explicit

    if policy.get("prefer_unclear_when_allowed", True) and "unclear" in allowed_values:
        return "unclear"

    if (
        policy.get("prefer_mixed_or_unclear_when_unclear_missing", True)
        and "mixed_or_unclear" in allowed_values
    ):
        return "mixed_or_unclear"

    missing_value = policy.get("missing_information_value")
    if isinstance(missing_value, str) and missing_value in allowed_values:
        return missing_value

    if not allowed_values:
        raise ValueError(f"Category has no allowed fallback values: {category_id}")

    return sorted(allowed_values)[0]


def fallback_recommendations(
    config: dict[str, object],
    topic_contract: dict[str, object] | None = None,
) -> dict[str, str]:
    allowed = allowed_values_by_category(config)
    return {
        category_id: recommended_fallback_value(
            category_id,
            allowed_values,
            topic_contract,
        )
        for category_id, allowed_values in allowed.items()
    }


def call_llm(
    config: dict[str, object],
    model: str,
    client: JSONLLMClient,
    topic_contract: dict[str, object] | None = None,
    trace_writer: LLMTraceWriter | None = None,
) -> tuple[dict[str, object], list[Path]]:
    prompt = render_generate_tagging_rules_prompt(
        config,
        topic_contract,
        fallback_recommendations(config, topic_contract),
    )
    result = client.create_json(
        model=model,
        system_message=SYSTEM_MESSAGE,
        prompt=prompt,
        schema_name="tagging_rules",
        schema=RULE_RESPONSE_SCHEMA,
        step_name=STEP.name,
        call_id="rules",
        trace_writer=trace_writer,
    )
    trace_paths = result.trace_paths.as_list() if result.trace_paths else []
    return result.parsed, trace_paths


def repair_rules(
    config: dict[str, object],
    result: dict[str, object],
    topic_contract: dict[str, object] | None = None,
) -> tuple[dict[str, object], list[str]]:
    """Repair semantically invalid LLM rules using deterministic config policy."""
    allowed = allowed_values_by_category(config)
    required_flags = required_by_category(config)
    configured_selection = selection_by_category(config)
    category_dependencies = applies_when_by_category(config)
    recommended = fallback_recommendations(config, topic_contract)
    rule_list = result.get("rules")
    if not isinstance(rule_list, list):
        raise ValueError("LLM response must contain a rules list.")

    rules_by_id: dict[str, dict[str, object]] = {}
    warnings = []
    for rule in rule_list:
        if not isinstance(rule, dict):
            warnings.append("Skipped non-object rule.")
            continue

        category_id = str(rule.get("category_id") or "")
        if category_id not in allowed:
            warnings.append(f"Skipped unknown category rule: {category_id}")
            continue

        if category_id in rules_by_id:
            warnings.append(f"Skipped duplicate rule for category: {category_id}")
            continue

        rules_by_id[category_id] = dict(rule)

    repaired_rules = []
    for category_id in ordered_category_ids(config):
        rule = rules_by_id.get(category_id)
        if rule is None:
            rule = {
                "category_id": category_id,
                "selection": configured_selection[category_id] or "single",
                "required": required_flags[category_id],
                "fallback_value": recommended[category_id],
                "reason": "Defaulted by pipeline because the LLM omitted this category.",
            }
            warnings.append(f"Added missing rule for category: {category_id}")

        selection = rule.get("selection")
        if selection not in VALID_CATEGORY_SELECTIONS:
            repaired_selection = configured_selection[category_id] or "single"
            rule["selection"] = repaired_selection
            warnings.append(
                f"Repaired invalid selection for category: {category_id}"
            )

        if configured_selection[category_id] is not None:
            configured = configured_selection[category_id]
            if rule.get("selection") != configured:
                rule["selection"] = configured
                warnings.append(
                    f"Repaired selection from category config for: {category_id}"
                )

        fallback_value = rule.get("fallback_value")
        if fallback_value not in allowed[category_id]:
            rule["fallback_value"] = recommended[category_id]
            reason = str(rule.get("reason") or "").strip()
            repair_reason = (
                " Pipeline replaced an invalid fallback_value with the "
                "topic-contract recommendation."
            )
            rule["reason"] = f"{reason}{repair_reason}".strip()
            warnings.append(
                "Repaired invalid fallback_value for "
                f"{category_id}: {fallback_value} -> {recommended[category_id]}"
            )

        if required_flags[category_id] and not rule.get("required"):
            rule["required"] = True
            warnings.append(f"Repaired required flag for category: {category_id}")

        applies_when = category_dependencies[category_id]
        if applies_when is not None:
            rule["applies_when"] = applies_when

        repaired_rules.append(rule)

    return {"rules": repaired_rules}, warnings


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
            raise ValueError(f"Invalid fallback_value for {category_id}: {fallback_value}")

        if rule.get("selection") not in VALID_CATEGORY_SELECTIONS:
            raise ValueError(f"Invalid selection for {category_id}: {rule.get('selection')}")

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


def run(
    config_path: Path,
    output_path: Path,
    model: str,
    topic_contract_path: Path | None = None,
    client: JSONLLMClient | None = None,
    trace_dir: Path | None = None,
) -> StepResult:
    config = load_json(config_path)
    topic_contract = load_topic_contract(topic_contract_path) if topic_contract_path else None
    trace_writer = LLMTraceWriter(trace_dir) if trace_dir is not None else None
    result, trace_paths = call_llm(
        config,
        model,
        client or OpenAIResponsesClient(),
        topic_contract,
        trace_writer,
    )
    result, warnings = repair_rules(config, result, topic_contract)
    validate_rules(config, result)
    write_output(output_path, config_path, model, result)
    return StepResult(
        step_name=STEP.name,
        inputs={"tagging_config_json": config_path},
        outputs={"tagging_rules_json": output_path},
        row_counts={"rules": len(result["rules"])},
        warnings=warnings,
        trace_paths=trace_paths,
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
    parser.add_argument(
        "--topic-contract",
        default=None,
        help="Optional topic contract YAML for fallback policy in the prompt.",
    )
    parser.add_argument(
        "--trace-dir",
        default=None,
        help="Optional directory where prompt/response traces are written.",
    )
    args = parser.parse_args()

    load_dotenv()

    model = args.model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    trace_dir = Path(args.trace_dir) if args.trace_dir else None
    topic_contract_path = Path(args.topic_contract) if args.topic_contract else None
    result = run(
        Path(args.config),
        Path(args.output),
        model,
        topic_contract_path,
        trace_dir=trace_dir,
    )

    print("Generated fixed tagging rules")
    print(f"Rules: {result.row_counts['rules']}")
    print(f"Wrote {args.output}")
