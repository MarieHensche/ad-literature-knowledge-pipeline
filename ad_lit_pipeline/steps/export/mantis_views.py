from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.mantis.projection import export_mantis_views


STEP = StepSpec(
    name="export_mantis_views",
    inputs=["versioned_records_jsonl"],
    outputs=[
        "mantis_paper_csv",
        "mantis_verified_claim_csv",
        "mantis_verified_gap_csv",
        "mantis_export_profiles",
        "mantis_export_reports",
    ],
    uses_llm=False,
    description=(
        "Create validated paper, verified-claim, and verified-open-gap Mantis views."
    ),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run(
    input_path: Path,
    output_directory: Path,
    *,
    producing_run_id: str,
    created_at: str | None = None,
) -> StepResult:
    views = export_mantis_views(
        input_path,
        output_directory,
        producing_run_id=producing_run_id,
        created_at=created_at or _now(),
    )
    by_kind = {view.record_kind: view for view in views}
    outputs = {
        "mantis_paper_csv": by_kind["paper"].csv_path,
        "mantis_verified_claim_csv": by_kind["verified_claim"].csv_path,
        "mantis_verified_gap_csv": by_kind["verified_gap"].csv_path,
    }
    for view in views:
        outputs[f"mantis_{view.record_kind}_profile"] = view.profile_path
        outputs[f"mantis_{view.record_kind}_report"] = view.report_path
    return StepResult(
        step_name=STEP.name,
        inputs={"versioned_records_jsonl": input_path},
        outputs=outputs,
        row_counts={f"{view.record_kind}_rows": view.row_count for view in views},
        metadata={
            "profile_version": "1.0.0",
            "compatibility_version": "1.0.0",
            "publication_performed": False,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export audited versioned-record views for Mantis."
    )
    parser.add_argument("--input", required=True, help="Versioned records JSONL.")
    parser.add_argument("--output-dir", required=True, help="Output directory.")
    parser.add_argument("--run-id", required=True, help="Producing run identifier.")
    parser.add_argument(
        "--created-at",
        help="Optional fixed UTC timestamp for reproducible builds.",
    )
    args = parser.parse_args()
    result = run(
        Path(args.input),
        Path(args.output_dir),
        producing_run_id=args.run_id,
        created_at=args.created_at,
    )
    for key, count in sorted(result.row_counts.items()):
        print(f"{key}: {count}")


if __name__ == "__main__":
    main()
