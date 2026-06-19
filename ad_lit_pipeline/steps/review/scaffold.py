from __future__ import annotations

from pathlib import Path

from ad_lit_pipeline.core.step import StepResult, StepSpec


STEP_SPECS = {
    "normalize_review_config": StepSpec(
        name="normalize_review_config",
        inputs=["topic_contract_yaml"],
        outputs=["review_config_normalized_json"],
        uses_llm=False,
        description="Normalize optional literature-review settings.",
    ),
    "extract_review_labels": StepSpec(
        name="extract_review_labels",
        inputs=["scope_screened_full_text_csv", "extraction_filled_csv"],
        outputs=["review_labels_raw_csv"],
        uses_llm=True,
        description="Extract paper-level labels used only for review generation.",
    ),
    "normalize_review_label_values": StepSpec(
        name="normalize_review_label_values",
        inputs=["review_labels_raw_csv", "review_config_normalized_json"],
        outputs=["review_label_values_json"],
        uses_llm=False,
        description="Normalize auto-discovered review label values.",
    ),
    "review_review_label_values": StepSpec(
        name="review_review_label_values",
        inputs=["review_label_values_json"],
        outputs=["review_label_values_review_yaml"],
        uses_llm=False,
        description="Optional human review gate for generated review label values.",
    ),
    "validate_review_labels": StepSpec(
        name="validate_review_labels",
        inputs=["review_labels_raw_csv", "review_label_values_json"],
        outputs=["review_quality_report_csv"],
        uses_llm=False,
        description="Validate review labels before evidence-map construction.",
    ),
    "build_review_evidence_map": StepSpec(
        name="build_review_evidence_map",
        inputs=["review_labels_raw_csv", "extraction_filled_csv"],
        outputs=["review_evidence_map_json"],
        uses_llm=False,
        description="Aggregate paper labels into citation-linked evidence packets.",
    ),
    "synthesize_review_sections": StepSpec(
        name="synthesize_review_sections",
        inputs=["review_evidence_map_json"],
        outputs=["review_sections_json"],
        uses_llm=True,
        description="Draft literature-review sections from evidence packets.",
    ),
    "assemble_literature_review": StepSpec(
        name="assemble_literature_review",
        inputs=["review_sections_json"],
        outputs=["literature_review_md"],
        uses_llm=False,
        description="Assemble the generated sections into a Markdown review.",
    ),
}


def run_scaffold_step(
    step_name: str,
    inputs: dict[str, Path],
    outputs: dict[str, Path],
) -> StepResult:
    if step_name not in STEP_SPECS:
        raise ValueError(f"Unknown review scaffold step: {step_name}")

    return StepResult(
        step_name=step_name,
        inputs=inputs,
        outputs=outputs,
        error=(
            "Literature-review generation is scaffolded but not implemented yet. "
            "Use --dry-run to inspect the optional review branch; later phases "
            "will add paper-level extraction and synthesis."
        ),
        metadata={"implementation_phase": "scaffold"},
    )
