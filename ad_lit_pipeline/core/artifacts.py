from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MainPipelineArtifacts:
    """Derived artifact paths for the main tagging pipeline."""

    raw_papers_csv: Path
    normalized_papers_csv: Path
    scope_screened_csv: Path
    scope_screened_full_text_csv: Path
    full_text_manifest_csv: Path
    tagging_categories_review_yaml: Path
    tagging_config_normalized_json: Path
    tagging_rules_json: Path
    extraction_filled_csv: Path
    extraction_audit_csv: Path
    mantis_ready_csv: Path


@dataclass(frozen=True)
class CollectionArtifacts:
    """Derived artifact paths for the collection workflow."""

    review_overviews_jsonl: Path
    review_overviews_full_text_jsonl: Path
    review_full_text_manifest_csv: Path
    plan_json: Path
    candidates_jsonl: Path
    deduped_candidates_jsonl: Path
    candidate_screening_csv: Path
    calibration_papers_csv: Path
    calibration_papers_full_text_csv: Path
    calibration_full_text_manifest_csv: Path
    papers_csv: Path


def processed_path(collection: str, suffix: str, base_dir: Path = Path(".")) -> Path:
    """Return the conventional processed artifact path for a collection."""
    return base_dir / "data" / "processed" / f"{collection}_{suffix}"


def raw_path(collection: str, suffix: str, base_dir: Path = Path(".")) -> Path:
    """Return the conventional raw artifact path for a collection."""
    return base_dir / "data" / "raw" / f"{collection}_{suffix}"


def plan_path(collection: str, base_dir: Path = Path(".")) -> Path:
    """Return the conventional collection plan path for a collection."""
    return base_dir / "data" / "collection_plans" / f"{collection}_plan.json"


def main_pipeline_artifacts(
    collection: str,
    base_dir: Path = Path("."),
) -> MainPipelineArtifacts:
    """Build all conventional main-pipeline artifact paths."""
    return MainPipelineArtifacts(
        raw_papers_csv=raw_path(collection, "papers.csv", base_dir),
        normalized_papers_csv=processed_path(
            collection, "papers_normalized.csv", base_dir
        ),
        scope_screened_csv=processed_path(collection, "scope_screened.csv", base_dir),
        scope_screened_full_text_csv=processed_path(
            collection, "scope_screened_full_text.csv", base_dir
        ),
        full_text_manifest_csv=processed_path(
            collection, "full_text_manifest.csv", base_dir
        ),
        tagging_categories_review_yaml=processed_path(
            collection, "tagging_categories_review.yaml", base_dir
        ),
        tagging_config_normalized_json=processed_path(
            collection, "tagging_config_normalized.json", base_dir
        ),
        tagging_rules_json=processed_path(collection, "tagging_rules.json", base_dir),
        extraction_filled_csv=processed_path(
            collection, "extraction_filled.csv", base_dir
        ),
        extraction_audit_csv=processed_path(
            collection, "extraction_audit.csv", base_dir
        ),
        mantis_ready_csv=processed_path(collection, "mantis_ready.csv", base_dir),
    )


def collection_artifacts(
    collection: str,
    base_dir: Path = Path("."),
) -> CollectionArtifacts:
    """Build all conventional collection-workflow artifact paths."""
    return CollectionArtifacts(
        review_overviews_jsonl=raw_path(
            collection, "review_overviews.jsonl", base_dir
        ),
        review_overviews_full_text_jsonl=raw_path(
            collection, "review_overviews_full_text.jsonl", base_dir
        ),
        review_full_text_manifest_csv=raw_path(
            collection, "review_full_text_manifest.csv", base_dir
        ),
        plan_json=plan_path(collection, base_dir),
        candidates_jsonl=raw_path(collection, "openalex_candidates.jsonl", base_dir),
        deduped_candidates_jsonl=raw_path(
            collection, "openalex_candidates_deduped.jsonl", base_dir
        ),
        candidate_screening_csv=raw_path(
            collection, "candidate_screening.csv", base_dir
        ),
        calibration_papers_csv=raw_path(
            collection, "calibration_papers.csv", base_dir
        ),
        calibration_papers_full_text_csv=raw_path(
            collection, "calibration_papers_full_text.csv", base_dir
        ),
        calibration_full_text_manifest_csv=raw_path(
            collection, "calibration_full_text_manifest.csv", base_dir
        ),
        papers_csv=raw_path(collection, "papers.csv", base_dir),
    )
