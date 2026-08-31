from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import unquote

from ad_lit_pipeline.cli.run_collection import build_parser as collection_parser
from ad_lit_pipeline.cli.run_pipeline import build_parser as main_parser
from ad_lit_pipeline.core.registry import PIPELINE_SPECS, STEP_CATALOG


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
TECHNICAL_SUMMARY = ROOT / "docs" / "technical_summary.md"
PIPELINE_REGISTRY_DOC = ROOT / "docs" / "pipeline_registry.md"
SUPERSEDED_BOOTSTRAP_PLAN = (
    ROOT / "docs" / "topic_contract_bootstrap_refinement_plan.md"
)
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def normalized_text(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def run_help(parser: argparse.ArgumentParser) -> str:
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return subparsers.choices["run"].format_help()


def test_technical_docs_track_registry_shape_and_named_pipelines() -> None:
    summary = normalized_text(TECHNICAL_SUMMARY)
    registry_doc = normalized_text(PIPELINE_REGISTRY_DOC)

    for text in (summary, registry_doc):
        assert f"{len(STEP_CATALOG)} registered steps" in text
        assert f"{len(PIPELINE_SPECS)} named pipelines" in text

    for pipeline_name in PIPELINE_SPECS:
        assert f"`{pipeline_name}`" in summary
        assert f"`{pipeline_name}`" in registry_doc


def test_operator_docs_cover_optional_public_workflows_and_boundaries() -> None:
    required_terms = (
        "--export-knowledge",
        "--extract-knowledge-findings",
        "--generate-review",
        "--review-review-label-values",
        "export_mantis_views",
        "publish_mantis_views",
        "preliminary",
        "complete v1 record",
    )
    for path in (README, TECHNICAL_SUMMARY):
        content = path.read_text(encoding="utf-8")
        for term in required_terms:
            assert term in content, f"{path.relative_to(ROOT)} omits {term!r}"


def test_cli_help_does_not_claim_collection_calibration_is_assembled() -> None:
    main_help = normalized_text_from_string(run_help(main_parser()))
    collection_help = normalized_text_from_string(run_help(collection_parser()))

    assert "selected included primary-paper full texts" in main_help
    assert "default assembled collection workflow does not run" in collection_help
    assert "New collection runs calibrate" not in main_help


def normalized_text_from_string(value: str) -> str:
    return " ".join(value.split())


def test_obsolete_scaffold_is_removed_and_old_plan_is_visibly_superseded() -> None:
    assert not (ROOT / "ad_lit_pipeline" / "steps" / "review" / "scaffold.py").exists()
    content = SUPERSEDED_BOOTSTRAP_PLAN.read_text(encoding="utf-8")
    assert "Status: superseded" in content
    assert "Living gap-discovery implementation plan" in content
    assert "former implementation instructions" in content


def test_local_markdown_links_resolve() -> None:
    markdown_files = (README, *sorted((ROOT / "docs").glob("*.md")))
    unresolved: list[str] = []

    for source in markdown_files:
        content = source.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(content):
            target = raw_target.strip().strip("<>")
            if not target or target.startswith("#"):
                continue
            if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
                continue
            path_text = unquote(target.split("#", 1)[0])
            resolved = (source.parent / path_text).resolve()
            if not resolved.exists():
                unresolved.append(
                    f"{source.relative_to(ROOT)} -> {raw_target}"
                )

    assert unresolved == []
