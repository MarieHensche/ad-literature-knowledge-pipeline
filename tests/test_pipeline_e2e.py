from __future__ import annotations

import csv
import json
from pathlib import Path

from ad_lit_pipeline.core.manifest import ManifestRecorder
from ad_lit_pipeline.core.registry import MAIN_PIPELINE
from ad_lit_pipeline.core.runner import default_trace_dir, run_selected_steps
from ad_lit_pipeline.llm.client import StaticJSONClient
from ad_lit_pipeline.steps.export import mantis
from ad_lit_pipeline.steps.full_text import prepare as prepare_full_text
from ad_lit_pipeline.steps.metadata import normalize
from ad_lit_pipeline.steps.screening import rule_based_scope
from ad_lit_pipeline.steps.tagging import audit, generate_rules, normalize_config, tag_papers


ROOT = Path(__file__).resolve().parents[1]
TOPIC_CONTRACT = ROOT / "configs/topics/early_detection_ad.yaml"


def _write_input(path: Path, full_text_path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "paper_id",
                "title",
                "year",
                "doi",
                "abstract",
                "authors",
                "venue",
                "source",
                "full_text_path",
                "notes",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "paper_id": "paper-e2e",
                "title": "Early Detection of Mild Cognitive Impairment Using Speech",
                "year": "2025",
                "doi": "10.1000/e2e",
                "abstract": (
                    "We classify mild cognitive impairment from speech for early "
                    "detection."
                ),
                "authors": "Example Author",
                "venue": "Fixture Journal",
                "source": "hermetic_fixture",
                "full_text_path": str(full_text_path),
                "notes": "preserve-this-provenance",
            }
        )


def _rules_response(config_path: Path) -> dict[str, object]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    rules = []
    for category in config["categories"]:
        first_value = category["allowed_values"][0]["value"]
        rules.append(
            {
                "category_id": category["category_id"],
                "selection": category.get("selection", "single"),
                "required": bool(category.get("required", False)),
                "fallback_value": first_value,
                "reason": "Deterministic hermetic test rule.",
            }
        )
    return {"rules": rules}


def _tag_response(config_path: Path) -> dict[str, object]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    response: dict[str, object] = {
        "paper_id": "paper-e2e",
        "main_knowledge_claim": (
            "Speech features support early detection of mild cognitive impairment."
        ),
    }
    for category in config["categories"]:
        response[category["category_id"]] = [
            category["allowed_values"][0]["value"]
        ]
    return response


def test_main_pipeline_succeeds_end_to_end_with_hermetic_llm_clients(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "raw/papers.csv"
    full_text = tmp_path / "raw/paper.txt"
    full_text.parent.mkdir(parents=True, exist_ok=True)
    full_text.write_text(
        (
            "Methods and results. Speech and language features were used to "
            "classify mild cognitive impairment for early detection. "
        )
        * 30,
        encoding="utf-8",
    )
    _write_input(raw, full_text)

    processed = tmp_path / "processed"
    normalized = processed / "normalized.csv"
    screened = processed / "screened.csv"
    with_text = processed / "with_text.csv"
    full_text_manifest = processed / "full_text_manifest.csv"
    normalized_config = processed / "tagging_config.json"
    rules = processed / "tagging_rules.json"
    filled = processed / "filled.csv"
    audit_path = processed / "audit.csv"
    mantis_path = processed / "mantis.csv"

    provenance = {
        "invocation": {
            "selected_steps": list(MAIN_PIPELINE),
            "pipeline_steps": list(MAIN_PIPELINE),
            "resume_compatibility_options": {"fixture": "hermetic"},
        }
    }
    manifest = ManifestRecorder.create(
        collection="hermetic",
        pipeline_name="main",
        runs_dir=tmp_path / "runs",
        run_id="main-e2e",
        topic_contract_path=TOPIC_CONTRACT,
        model="static-json",
        provenance=provenance,
    )
    trace_dir = default_trace_dir(manifest)

    def run_generate_rules():
        return generate_rules.run(
            normalized_config,
            rules,
            "static-json",
            TOPIC_CONTRACT,
            StaticJSONClient([_rules_response(normalized_config)]),
            trace_dir,
        )

    def run_tag_papers():
        return tag_papers.run(
            with_text,
            normalized_config,
            rules,
            filled,
            "static-json",
            TOPIC_CONTRACT,
            StaticJSONClient([_tag_response(normalized_config)]),
            trace_dir,
        )

    step_functions = {
        "normalize_metadata": lambda: normalize.run(raw, normalized),
        "screen_scope": lambda: rule_based_scope.run(
            normalized,
            screened,
            TOPIC_CONTRACT,
        ),
        "prepare_full_text": lambda: prepare_full_text.run(
            screened,
            with_text,
            full_text_manifest,
            tmp_path / "cache",
        ),
        "normalize_tagging_config": lambda: normalize_config.run(
            normalized_config,
            topic_contract_path=TOPIC_CONTRACT,
        ),
        "generate_tagging_rules": run_generate_rules,
        "tag_papers": run_tag_papers,
        "audit_extraction": lambda: audit.run(
            filled,
            normalized_config,
            rules,
            audit_path,
        ),
        "export_mantis": lambda: mantis.run(filled, mantis_path),
    }

    status = run_selected_steps(MAIN_PIPELINE, step_functions, manifest)

    assert status == "succeeded"
    payload = ManifestRecorder.load(manifest.manifest_path)
    assert payload["status"] == "succeeded"
    assert [step["step_name"] for step in payload["steps"]] == list(MAIN_PIPELINE)
    assert {step["status"] for step in payload["steps"]} == {"succeeded"}
    assert {step["attempt_id"] for step in payload["steps"]} == {"attempt-0001"}
    assert all(
        output["exists"] and output["sha256"]
        for step in payload["steps"]
        for output in step["outputs"].values()
    )

    trace_artifacts = [
        artifact
        for step in payload["steps"]
        for artifact in step["trace_artifacts"]
    ]
    assert len(trace_artifacts) == 12
    assert all("attempt-0001" in artifact["path"] for artifact in trace_artifacts)
    assert all(artifact["exists"] and artifact["sha256"] for artifact in trace_artifacts)

    with filled.open(newline="", encoding="utf-8") as handle:
        tagged_rows = list(csv.DictReader(handle))
    with mantis_path.open(newline="", encoding="utf-8") as handle:
        mantis_rows = list(csv.DictReader(handle))
    assert len(tagged_rows) == 1
    assert tagged_rows[0]["paper_id"] == "paper-e2e"
    assert tagged_rows[0]["notes"] == "preserve-this-provenance"
    assert tagged_rows[0]["full_text_status"] == "local_text_extracted"
    assert len(mantis_rows) == 1
    assert mantis_rows[0]["paper_id"] == "paper-e2e"
