from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.llm.client import JSONLLMClient, OpenAIResponsesClient
from ad_lit_pipeline.llm.schemas import paper_tags_schema
from ad_lit_pipeline.llm.trace import LLMTraceWriter
from ad_lit_pipeline.prompts.render import render_tag_paper_prompt
from ad_lit_pipeline.steps.full_text.evidence import read_text_evidence
from ad_lit_pipeline.topics.contract import (
    FALLBACK_TAG_VALUES,
    load_topic_contract,
    normalize_tagging_label,
)


STEP = StepSpec(
    name="tag_papers",
    inputs=[
        "scope_screened_full_text_csv",
        "tagging_config_json",
        "tagging_rules_json",
    ],
    outputs=["extraction_filled_csv"],
    uses_llm=True,
    description="Tag included papers with fixed knowledge tags using an LLM.",
)

SYSTEM_MESSAGE = "You tag scientific papers using fixed ontology rules as strict JSON."


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


def read_papers(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def read_included_papers(path: Path) -> list[dict[str, str]]:
    _, rows = read_papers(path)
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


def category_by_id(config: dict[str, object]) -> dict[str, dict[str, object]]:
    return {
        str(category["category_id"]): category
        for category in categories_from_config(config)
    }


def allowed_values_by_category(config: dict[str, object]) -> dict[str, set[str]]:
    allowed = {}
    for category in categories_from_config(config):
        category_id = category["category_id"]
        allowed[category_id] = {
            value["value"] for value in category.get("allowed_values", [])
        }
    return allowed


def is_fallback_tag_value(value: object) -> bool:
    return normalize_tagging_label(str(value or "")) in FALLBACK_TAG_VALUES


def remove_fallback_values_when_concrete_values_exist(values: list[object]) -> list[object]:
    concrete_values = [value for value in values if not is_fallback_tag_value(value)]
    if concrete_values and len(concrete_values) != len(values):
        return concrete_values
    return values


def applies_when_for_category(
    category_id: str,
    categories: dict[str, dict[str, object]],
    rules: dict[str, dict[str, object]],
) -> dict[str, object] | None:
    rule_dependency = rules.get(category_id, {}).get("applies_when")
    if isinstance(rule_dependency, dict):
        return rule_dependency

    category_dependency = categories.get(category_id, {}).get("applies_when")
    if isinstance(category_dependency, dict):
        return category_dependency

    return None


def category_applies(
    tagged: dict[str, object],
    dependency: dict[str, object] | None,
) -> bool:
    if dependency is None:
        return True

    parent_id = str(dependency.get("category_id") or "")
    parent_values = tagged.get(parent_id)
    if not isinstance(parent_values, list):
        return False

    triggering_values = {
        str(value) for value in dependency.get("values", []) if str(value)
    }
    return any(value in triggering_values for value in parent_values)


def paper_text(paper: dict[str, str]) -> dict[str, str]:
    full_text_evidence = read_text_evidence(paper.get("full_text_text_path", ""))
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
        "full_text_status": paper.get("full_text_status", ""),
        "full_text_source": paper.get("full_text_source", ""),
        "full_text_url": paper.get("full_text_url", ""),
        "full_text_text_path": paper.get("full_text_text_path", ""),
        "full_text_available_for_tagging": "yes" if full_text_evidence else "no",
        "full_text_evidence": full_text_evidence,
    }


def call_llm(
    paper: dict[str, str],
    config: dict[str, object],
    rules: dict[str, object],
    model: str,
    client: JSONLLMClient,
    topic_contract: dict[str, object] | None = None,
    trace_writer: LLMTraceWriter | None = None,
) -> tuple[dict[str, object], list[Path]]:
    prompt = render_tag_paper_prompt(paper_text(paper), config, rules, topic_contract)
    result = client.create_json(
        model=model,
        system_message=SYSTEM_MESSAGE,
        prompt=prompt,
        schema_name="paper_tags",
        schema=paper_tags_schema(config),
        step_name=STEP.name,
        call_id=paper.get("paper_id", "paper"),
        trace_writer=trace_writer,
    )
    trace_paths = result.trace_paths.as_list() if result.trace_paths else []
    return result.parsed, trace_paths


def validate_tagged_row(
    tagged: dict[str, object],
    config: dict[str, object],
    rules: dict[str, object],
) -> None:
    allowed = allowed_values_by_category(config)
    categories = category_by_id(config)
    rule_map = rules_by_category(rules)

    for category_id, allowed_values in allowed.items():
        values = tagged.get(category_id)

        if not isinstance(values, list):
            raise ValueError(f"{category_id} must be a list.")

        invalid = [value for value in values if value not in allowed_values]
        if invalid:
            raise ValueError(f"{category_id} has invalid value(s): {invalid}")

        values = remove_fallback_values_when_concrete_values_exist(values)
        tagged[category_id] = values

        rule = rule_map[category_id]
        if rule["selection"] == "single" and len(values) > 1:
            tagged[category_id] = [values[0]]

    for category_id, allowed_values in allowed.items():
        values = tagged.get(category_id)
        if not isinstance(values, list):
            raise ValueError(f"{category_id} must be a list.")

        rule = rule_map[category_id]
        dependency = applies_when_for_category(category_id, categories, rule_map)
        if not category_applies(tagged, dependency):
            tagged[category_id] = []
            continue

        if not values and rule.get("required"):
            fallback_value = rule.get("fallback_value")
            if fallback_value in allowed_values:
                tagged[category_id] = [fallback_value]
                values = tagged[category_id]
            else:
                raise ValueError(f"{category_id} has no selected value.")

        if not values:
            tagged[category_id] = []
            continue


def output_columns(
    input_columns: list[str],
    config: dict[str, object],
) -> list[str]:
    columns = list(input_columns)
    if "main_knowledge_claim" not in columns:
        columns.append("main_knowledge_claim")

    for category in categories_from_config(config):
        category_id = str(category["category_id"])
        if category_id not in columns:
            columns.append(category_id)

    return columns


def flatten_tagged_row(
    paper: dict[str, str],
    tagged: dict[str, object],
    config: dict[str, object],
) -> dict[str, str]:
    row = dict(paper)
    row["main_knowledge_claim"] = str(tagged.get("main_knowledge_claim", ""))

    for category in categories_from_config(config):
        category_id = category["category_id"]
        row[str(category_id)] = "; ".join(tagged[category_id])

    return row


def write_rows(
    output_path: Path,
    rows: list[dict[str, str]],
    config: dict[str, object],
    fieldnames: list[str],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def run(
    papers_path: Path,
    config_path: Path,
    rules_path: Path,
    output_path: Path,
    model: str,
    topic_contract_path: Path | None = None,
    client: JSONLLMClient | None = None,
    trace_dir: Path | None = None,
) -> StepResult:
    input_columns, all_papers = read_papers(papers_path)
    papers = [paper for paper in all_papers if paper.get("scope_decision") == "include"]
    config = load_json(config_path)
    rules = load_json(rules_path)
    topic_contract = load_topic_contract(topic_contract_path) if topic_contract_path else None
    llm_client = client or OpenAIResponsesClient()
    trace_writer = LLMTraceWriter(trace_dir) if trace_dir is not None else None

    rows = []
    all_trace_paths: list[Path] = []
    warnings = []

    for index, paper in enumerate(papers, start=1):
        paper_id = paper.get("paper_id") or f"row_{index}"
        print(f"Tagging paper {index}/{len(papers)}: {paper_id}")

        try:
            tagged, trace_paths = call_llm(
                paper,
                config,
                rules,
                model,
                llm_client,
                topic_contract,
                trace_writer,
            )
            validate_tagged_row(tagged, config, rules)
            rows.append(flatten_tagged_row(paper, tagged, config))
            all_trace_paths.extend(trace_paths)

        except ValueError as error:
            # LLM failed or validation failed - skip this paper and continue with warning
            error_msg = str(error)
            warning = f"Failed to tag paper '{paper_id}' after retry (skipped): {error_msg}"
            warnings.append(warning)
            print(f"  Warning: {warning}")
            # Paper is skipped, not added to rows

    write_rows(output_path, rows, config, output_columns(input_columns, config))
    return StepResult(
        step_name=STEP.name,
        inputs={
            "scope_screened_full_text_csv": papers_path,
            "tagging_config_json": config_path,
            "tagging_rules_json": rules_path,
        },
        outputs={"extraction_filled_csv": output_path},
        row_counts={"tagged_papers": len(rows)},
        trace_paths=all_trace_paths,
        warnings=warnings,
    )


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
    parser.add_argument(
        "--topic-contract",
        default=None,
        help="Optional topic contract YAML for scope text in the prompt.",
    )
    parser.add_argument(
        "--trace-dir",
        default=None,
        help="Optional directory where prompt/response traces are written.",
    )
    args = parser.parse_args()

    load_dotenv()

    model = args.model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    topic_contract_path = Path(args.topic_contract) if args.topic_contract else None
    trace_dir = Path(args.trace_dir) if args.trace_dir else None
    result = run(
        Path(args.papers),
        Path(args.config),
        Path(args.rules),
        Path(args.output),
        model,
        topic_contract_path,
        trace_dir=trace_dir,
    )

    print(f"Tagged papers: {result.row_counts['tagged_papers']}")
    print(f"Wrote {args.output}")
