from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from ad_lit_pipeline.core.errors import ValidationError
from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.mantis.publisher import (
    CommandRunner,
    PublicationDestination,
    failure_receipt,
    publish_csv,
)
from ad_lit_pipeline.records import (
    MantisExportProfile,
    MantisPublicationReceipt,
    record_from_dict,
    write_record_jsonl,
)
from ad_lit_pipeline.records.models import MantisPublicationStatus, MantisRecordKind


STEP = StepSpec(
    name="publish_mantis_views",
    inputs=[
        "mantis_paper_csv",
        "mantis_verified_claim_csv",
        "mantis_verified_gap_csv",
        "mantis_export_profiles",
    ],
    outputs=["mantis_publication_receipts_jsonl"],
    uses_llm=False,
    description="Optionally publish validated views using the pinned Mantis CLI.",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_profile(path: Path) -> MantisExportProfile:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Could not read Mantis profile {path}: {exc}") from exc
    record = record_from_dict(payload)
    if not isinstance(record, MantisExportProfile):
        raise ValidationError(f"Expected MantisExportProfile in {path}.")
    return record


def run(
    input_directory: Path,
    receipts_path: Path,
    *,
    publish: bool,
    producing_run_id: str,
    space_mode: str,
    space_id: str | None = None,
    space_name: str | None = None,
    map_name_prefix: str = "Scientific evidence",
    require_publication: bool = False,
    created_at: str | None = None,
    runner: CommandRunner | None = None,
) -> StepResult:
    if not publish:
        raise ValidationError(
            "Mantis publication requires the explicit --publish feature gate."
        )
    timestamp = created_at or _now()
    receipts: list[MantisPublicationReceipt] = []
    effective_mode = space_mode
    effective_space_id = space_id
    warnings: list[str] = []
    publication_inputs = []
    for kind in MantisRecordKind:
        prefix = f"mantis_{kind.value}_v1"
        csv_path = input_directory / f"{prefix}.csv"
        profile = _read_profile(input_directory / f"{prefix}.profile.json")
        publication_inputs.append((kind, csv_path, profile))

    for index, (kind, csv_path, profile) in enumerate(publication_inputs):
        destination = PublicationDestination(
            map_name=f"{map_name_prefix} - {kind.value.replace('_', ' ')}",
            space_mode=effective_mode,
            space_id=effective_space_id,
            space_name=space_name,
        )
        kwargs = {}
        if runner is not None:
            kwargs["runner"] = runner
        receipt = publish_csv(
            csv_path,
            profile,
            destination,
            enabled=True,
            producing_run_id=producing_run_id,
            created_at=timestamp,
            started_at=timestamp,
            completed_at=timestamp,
            **kwargs,
        )
        receipts.append(receipt)
        if receipt.publication_status is MantisPublicationStatus.SUCCEEDED:
            if effective_mode == "new":
                effective_mode = "existing"
                effective_space_id = receipt.space_id
        else:
            warnings.append(
                f"Mantis {kind.value} publication failed: "
                f"{receipt.error.code if receipt.error else 'unknown_error'}"
            )
            if effective_mode == "new":
                for skipped_kind, skipped_csv, skipped_profile in publication_inputs[
                    index + 1 :
                ]:
                    skipped_destination = PublicationDestination(
                        map_name=(
                            f"{map_name_prefix} - "
                            f"{skipped_kind.value.replace('_', ' ')}"
                        ),
                        space_mode="new",
                        space_name=space_name,
                    )
                    skipped = failure_receipt(
                        skipped_csv,
                        skipped_profile,
                        skipped_destination,
                        producing_run_id=producing_run_id,
                        created_at=timestamp,
                        started_at=timestamp,
                        completed_at=timestamp,
                        error_code="publication_dependency_failed",
                        error_message=(
                            "Publication was not attempted because creating the "
                            "shared Mantis space failed for an earlier view."
                        ),
                    )
                    receipts.append(skipped)
                    warnings.append(
                        f"Mantis {skipped_kind.value} publication was skipped: "
                        "publication_dependency_failed"
                    )
                break
    write_record_jsonl(receipts_path, receipts)
    failures = [
        receipt
        for receipt in receipts
        if receipt.publication_status is not MantisPublicationStatus.SUCCEEDED
    ]
    result = StepResult(
        step_name=STEP.name,
        inputs={"mantis_export_directory": input_directory},
        outputs={"mantis_publication_receipts_jsonl": receipts_path},
        row_counts={
            "publication_attempts": len(receipts),
            "successful_publications": len(receipts) - len(failures),
            "failed_publications": len(failures),
        },
        warnings=warnings,
        metadata={
            "feature_gate": "publish",
            "visibility": "private",
            "activate": False,
        },
    )
    if failures and require_publication:
        raise RuntimeError(
            "Mantis publication was required but failed; durable receipts were "
            f"written to {receipts_path}."
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Explicitly publish audited CSV views to a private Mantis space."
    )
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--receipts", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--require-publication", action="store_true")
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--space-id")
    destination.add_argument("--space-name")
    parser.add_argument("--map-name-prefix", default="Scientific evidence")
    parser.add_argument("--created-at")
    args = parser.parse_args()
    result = run(
        Path(args.input_dir),
        Path(args.receipts),
        publish=args.publish,
        producing_run_id=args.run_id,
        space_mode="existing" if args.space_id else "new",
        space_id=args.space_id,
        space_name=args.space_name,
        map_name_prefix=args.map_name_prefix,
        require_publication=args.require_publication,
        created_at=args.created_at,
    )
    print(
        f"Mantis publications: {result.row_counts['successful_publications']} "
        f"succeeded, {result.row_counts['failed_publications']} failed"
    )


if __name__ == "__main__":
    main()
