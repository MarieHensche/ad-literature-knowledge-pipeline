from __future__ import annotations

from itertools import product
from types import SimpleNamespace

import pytest

from ad_lit_pipeline.cli.run_collection import selected_collection_pipeline
from ad_lit_pipeline.cli.run_pipeline import selected_main_pipeline
from ad_lit_pipeline.core.registry import (
    COLLECTION_PIPELINE,
    COLLECTION_WITH_CONTRACT_PIPELINE,
    CONTRACT_BOOTSTRAP_PIPELINE,
    MAIN_PIPELINE,
    PIPELINE_SPECS,
    STEP_CATALOG,
    CollectionPipelineOptions,
    MainPipelineOptions,
    assemble_collection_pipeline,
    assemble_main_pipeline,
    step_spec,
    validate_pipeline_steps,
    validate_step_catalog,
)
from ad_lit_pipeline.core.runner import run_selected_steps
from ad_lit_pipeline.core.step import StepSpec
from pipeline_ui import server


MAIN_OPTION_FIELDS = (
    "calibrate_topic_contract",
    "review_tagging_categories",
    "export_knowledge",
    "extract_knowledge_findings",
    "extract_review_labels",
    "generate_review",
    "review_review_label_values",
)


def main_namespace(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        field: False for field in MAIN_OPTION_FIELDS
    }
    values.update({"only_step": None, "from_step": None})
    values.update(overrides)
    return SimpleNamespace(**values)


def collection_namespace(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "generate_topic_contract": False,
        "topic_contract": "configs/topics/example.yaml",
        "contract_bootstrap_only": False,
        "only_step": None,
        "from_step": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_catalog_registers_real_and_compatibility_steps_immutably() -> None:
    assert len(STEP_CATALOG) == 44
    assert step_spec("normalize_metadata").inputs == ["raw_papers_csv"]
    assert step_spec("prepare_calibration_full_text").outputs == [
        "calibration_papers_full_text_csv",
        "calibration_full_text_manifest_csv",
    ]
    assert "normalize_review_config" in STEP_CATALOG
    assert step_spec("materialize_corpus_snapshot").outputs == [
        "corpus_records_jsonl",
        "corpus_snapshot_integrity_json",
    ]
    assert tuple(PIPELINE_SPECS["main"].steps) == MAIN_PIPELINE

    with pytest.raises(TypeError):
        STEP_CATALOG["new_step"] = step_spec("normalize_metadata")  # type: ignore[index]
    with pytest.raises(TypeError):
        PIPELINE_SPECS["new_pipeline"] = PIPELINE_SPECS["main"]  # type: ignore[index]


def test_ui_config_exposes_the_authoritative_step_metadata() -> None:
    config = server.app_config()

    assert set(config["stepCatalog"]) == set(STEP_CATALOG)
    assert config["stepCatalog"]["tag_papers"]["dependencies"] == (
        "prepare_full_text",
        "normalize_review_config",
        "generate_tagging_rules",
    )
    assert config["stepCatalog"]["export_mantis"]["capabilities"] == [
        "mantis_export"
    ]


def test_catalog_declares_dependencies_and_capabilities() -> None:
    tag = step_spec("tag_papers")
    assert tag.dependencies == (
        "prepare_full_text",
        "normalize_review_config",
        "generate_tagging_rules",
    )
    assert tag.capabilities == frozenset({"llm", "network"})
    assert step_spec("fetch_candidates").capabilities == frozenset(
        {"network", "provider_access"}
    )
    assert step_spec("review_tagging_categories").capabilities == frozenset(
        {"human_review", "llm", "network"}
    )
    assert step_spec("export_mantis").capabilities == frozenset(
        {"mantis_export"}
    )
    assert step_spec("export_mantis_views").capabilities == frozenset(
        {"mantis_export"}
    )
    assert step_spec("publish_mantis_views").capabilities == frozenset(
        {"mantis_publish", "network"}
    )


def test_all_named_pipeline_specs_validate() -> None:
    validate_step_catalog()
    for pipeline in PIPELINE_SPECS.values():
        assert validate_pipeline_steps(
            pipeline.steps,
            pipeline_name=pipeline.name,
        ) == pipeline.steps


def test_pipeline_validation_rejects_unknown_duplicate_and_reversed_steps() -> None:
    with pytest.raises(ValueError, match="unknown steps"):
        validate_pipeline_steps(("normalize_metadata", "not_registered"))
    with pytest.raises(ValueError, match="duplicate steps"):
        validate_pipeline_steps(("normalize_metadata", "normalize_metadata"))
    with pytest.raises(ValueError, match="before dependency"):
        validate_pipeline_steps(("screen_scope", "normalize_metadata"))


def test_runner_rejects_missing_runtime_functions_before_execution() -> None:
    with pytest.raises(ValueError, match="no runtime implementation"):
        run_selected_steps(
            ("normalize_metadata",),
            {},
            None,  # type: ignore[arg-type]
        )


def test_catalog_validation_rejects_unknown_dependency_and_cycle() -> None:
    unknown = {
        "first": StepSpec(
            name="first",
            inputs=[],
            outputs=[],
            dependencies=("missing",),
        )
    }
    with pytest.raises(ValueError, match="unknown dependencies"):
        validate_step_catalog(unknown)

    cycle = {
        "first": StepSpec(
            name="first",
            inputs=[],
            outputs=[],
            dependencies=("second",),
        ),
        "second": StepSpec(
            name="second",
            inputs=[],
            outputs=[],
            dependencies=("first",),
        ),
    }
    with pytest.raises(ValueError, match="dependency cycle"):
        validate_step_catalog(cycle)


def test_main_assembler_preserves_frozen_key_orders() -> None:
    assert assemble_main_pipeline(MainPipelineOptions()) == MAIN_PIPELINE
    assert assemble_main_pipeline(
        MainPipelineOptions(export_knowledge=True)
    )[:6] == (
        "normalize_metadata",
        "screen_scope",
        "prepare_full_text",
        "export_knowledge_sources",
        "export_knowledge_evidence_excerpts",
        "normalize_tagging_config",
    )
    review = assemble_main_pipeline(
        MainPipelineOptions(
            review_tagging_categories=True,
            generate_review=True,
            review_review_label_values=True,
        )
    )
    assert review.index("review_tagging_categories") < review.index(
        "normalize_tagging_config"
    )
    assert review.index("filter_review_papers") < review.index(
        "normalize_review_config"
    )
    assert review.index("review_review_label_values") < review.index(
        "validate_review_labels"
    )
    assert review[-1] == "assemble_literature_review"


def test_every_main_cli_option_combination_uses_shared_assembler() -> None:
    for values in product((False, True), repeat=len(MAIN_OPTION_FIELDS)):
        option_values = dict(zip(MAIN_OPTION_FIELDS, values, strict=True))
        args = main_namespace(**option_values)
        expected = assemble_main_pipeline(MainPipelineOptions(**option_values))

        assert selected_main_pipeline(args) == list(expected)


def test_ui_main_variants_match_cli_pipeline_assembly() -> None:
    for tag_review, generate_review, review_values in product(
        (False, True),
        repeat=3,
    ):
        expected = selected_main_pipeline(
            main_namespace(
                review_tagging_categories=tag_review,
                generate_review=generate_review,
                review_review_label_values=review_values,
            )
        )
        actual = server.main_step_names(
            review_tagging_categories=tag_review,
            generate_review=generate_review,
            review_review_label_values=review_values,
        )
        assert actual == expected


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        (CollectionPipelineOptions(), COLLECTION_PIPELINE),
        (
            CollectionPipelineOptions(generate_topic_contract=True),
            COLLECTION_WITH_CONTRACT_PIPELINE,
        ),
        (
            CollectionPipelineOptions(topic_contract_supplied=False),
            COLLECTION_WITH_CONTRACT_PIPELINE,
        ),
        (
            CollectionPipelineOptions(contract_bootstrap_only=True),
            CONTRACT_BOOTSTRAP_PIPELINE,
        ),
        (
            CollectionPipelineOptions(requested_step="fetch_review_overviews"),
            COLLECTION_WITH_CONTRACT_PIPELINE,
        ),
    ],
)
def test_collection_assembler_preserves_current_variants(
    options: CollectionPipelineOptions,
    expected: tuple[str, ...],
) -> None:
    assert assemble_collection_pipeline(options) == expected


def test_ui_and_collection_cli_use_shared_pipeline_assembly() -> None:
    for generate_contract, bootstrap_only in product((False, True), repeat=2):
        ui_steps = server.collection_step_names(
            generate_contract,
            bootstrap_only,
        )
        cli_steps = selected_collection_pipeline(
            collection_namespace(
                generate_topic_contract=generate_contract,
                topic_contract=(None if generate_contract else "contract.yaml"),
                contract_bootstrap_only=bootstrap_only,
            )
        )
        assert ui_steps == cli_steps


def test_requested_optional_steps_activate_the_compatible_branch() -> None:
    assert "calibrate_topic_contract" in assemble_main_pipeline(
        MainPipelineOptions(requested_step="calibrate_topic_contract")
    )
    assert "extract_knowledge_findings" in assemble_main_pipeline(
        MainPipelineOptions(requested_step="extract_knowledge_findings")
    )
    review = assemble_main_pipeline(
        MainPipelineOptions(requested_step="extract_review_labels")
    )
    assert review[-2:] == ("filter_review_papers", "extract_review_labels")
