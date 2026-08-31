from __future__ import annotations

import json
from pathlib import Path

import pytest

from ad_lit_pipeline.core.errors import ValidationError
from ad_lit_pipeline.mantis.publisher import (
    CommandResult,
    PublicationDestination,
    build_create_map_command,
    publish_csv,
)
from ad_lit_pipeline.records import MantisExportProfile, record_from_dict, write_record_jsonl
from ad_lit_pipeline.records.models import MantisPublicationStatus
from ad_lit_pipeline.steps.export import publish_mantis
from ad_lit_pipeline.steps.export.mantis_views import run as export_views
from tests.mantis_fixtures import mantis_records


CREATED_AT = "2026-08-27T09:00:00Z"


def _prepare_views(tmp_path: Path) -> Path:
    source = tmp_path / "records.jsonl"
    output = tmp_path / "views"
    write_record_jsonl(source, mantis_records())
    export_views(
        source,
        output,
        producing_run_id="publisher-test",
        created_at=CREATED_AT,
    )
    return output


def _profile(directory: Path, kind: str = "paper") -> MantisExportProfile:
    payload = json.loads(
        (directory / f"mantis_{kind}_v1.profile.json").read_text(encoding="utf-8")
    )
    record = record_from_dict(payload)
    assert isinstance(record, MantisExportProfile)
    return record


def test_create_command_is_private_inactive_typed_and_credential_free(
    tmp_path: Path,
) -> None:
    views = _prepare_views(tmp_path)
    command = build_create_map_command(
        views / "mantis_paper_v1.csv",
        _profile(views),
        PublicationDestination(
            map_name="Papers",
            space_mode="existing",
            space_id="space-fixture",
        ),
    )

    assert command[:3] == ("mantis", "create", "map")
    assert "--private" in command
    assert "--no-activate" in command
    assert "--semantic-column" in command
    assert "--connection-column" not in command
    assert not any("key" in part.lower() or "token" in part.lower() for part in command)


def test_publication_requires_an_explicit_feature_gate(tmp_path: Path) -> None:
    views = _prepare_views(tmp_path)
    with pytest.raises(ValidationError, match="disabled"):
        publish_csv(
            views / "mantis_paper_v1.csv",
            _profile(views),
            PublicationDestination(
                map_name="Papers",
                space_mode="existing",
                space_id="space-fixture",
            ),
            enabled=False,
            producing_run_id="publisher-test",
            created_at=CREATED_AT,
            started_at=CREATED_AT,
            completed_at=CREATED_AT,
        )


def test_pinned_cli_success_creates_a_valid_publication_receipt(
    tmp_path: Path,
) -> None:
    views = _prepare_views(tmp_path)
    calls: list[tuple[str, ...]] = []

    def runner(command: tuple[str, ...]) -> CommandResult:
        calls.append(command)
        if command == ("mantis", "--version"):
            return CommandResult(0, "mantis 3.7.0\n", "")
        return CommandResult(
            0,
            '{"space_id":"space-fixture","map_id":"map-fixture"}\n',
            "",
        )

    receipt = publish_csv(
        views / "mantis_paper_v1.csv",
        _profile(views),
        PublicationDestination(
            map_name="Papers",
            space_mode="existing",
            space_id="space-fixture",
        ),
        enabled=True,
        producing_run_id="publisher-test",
        created_at=CREATED_AT,
        started_at=CREATED_AT,
        completed_at=CREATED_AT,
        runner=runner,
    )

    assert receipt.publication_status is MantisPublicationStatus.SUCCEEDED
    assert receipt.tool_version == "3.7.0"
    assert receipt.space_id == "space-fixture"
    assert receipt.map_id == "map-fixture"
    assert receipt.record_count == 1
    assert len(calls) == 2


def test_cli_mismatch_records_failure_and_preserves_csv(tmp_path: Path) -> None:
    views = _prepare_views(tmp_path)
    csv_path = views / "mantis_paper_v1.csv"
    before = csv_path.read_bytes()

    def runner(command: tuple[str, ...]) -> CommandResult:
        assert command == ("mantis", "--version")
        return CommandResult(0, "mantis 3.8.0\n", "")

    receipt = publish_csv(
        csv_path,
        _profile(views),
        PublicationDestination(
            map_name="Papers",
            space_mode="existing",
            space_id="space-fixture",
        ),
        enabled=True,
        producing_run_id="publisher-test",
        created_at=CREATED_AT,
        started_at=CREATED_AT,
        completed_at=CREATED_AT,
        runner=runner,
    )

    assert receipt.publication_status is MantisPublicationStatus.FAILED
    assert receipt.error is not None
    assert receipt.error.code == "unsupported_mantis_cli_version"
    assert csv_path.read_bytes() == before


def test_required_batch_failure_writes_receipt_before_raising(tmp_path: Path) -> None:
    views = _prepare_views(tmp_path)
    receipts = tmp_path / "receipts.jsonl"

    def runner(command: tuple[str, ...]) -> CommandResult:
        if command == ("mantis", "--version"):
            return CommandResult(0, "mantis 3.7.0\n", "")
        return CommandResult(
            1,
            "",
            "Authorization: Bearer a-secret-value-that-must-not-survive",
        )

    with pytest.raises(RuntimeError, match="durable receipts"):
        publish_mantis.run(
            views,
            receipts,
            publish=True,
            producing_run_id="publisher-test",
            space_mode="existing",
            space_id="space-fixture",
            require_publication=True,
            created_at=CREATED_AT,
            runner=runner,
        )

    assert receipts.is_file()
    payloads = [json.loads(line) for line in receipts.read_text().splitlines()]
    assert len(payloads) == 3
    assert payloads[0]["publication_status"] == "failed"
    assert "secret" not in payloads[0]["error"]["message"].lower()


def test_missing_csv_returns_a_failure_receipt_without_running_cli(
    tmp_path: Path,
) -> None:
    views = _prepare_views(tmp_path)
    calls = []

    def runner(command: tuple[str, ...]) -> CommandResult:
        calls.append(command)
        raise AssertionError("runner must not be called")

    receipt = publish_csv(
        views / "missing.csv",
        _profile(views),
        PublicationDestination(
            map_name="Papers",
            space_mode="existing",
            space_id="space-fixture",
        ),
        enabled=True,
        producing_run_id="publisher-test",
        created_at=CREATED_AT,
        started_at=CREATED_AT,
        completed_at=CREATED_AT,
        runner=runner,
    )

    assert receipt.publication_status is MantisPublicationStatus.FAILED
    assert receipt.error is not None
    assert receipt.error.code == "missing_mantis_view"
    assert receipt.record_count == 0
    assert calls == []


def test_unexpected_runner_error_returns_a_failure_receipt(tmp_path: Path) -> None:
    views = _prepare_views(tmp_path)

    def runner(command: tuple[str, ...]) -> CommandResult:
        raise RuntimeError("local runner exploded")

    receipt = publish_csv(
        views / "mantis_paper_v1.csv",
        _profile(views),
        PublicationDestination(
            map_name="Papers",
            space_mode="existing",
            space_id="space-fixture",
        ),
        enabled=True,
        producing_run_id="publisher-test",
        created_at=CREATED_AT,
        started_at=CREATED_AT,
        completed_at=CREATED_AT,
        runner=runner,
    )

    assert receipt.publication_status is MantisPublicationStatus.FAILED
    assert receipt.error is not None
    assert receipt.error.code == "mantis_publication_exception"


def test_new_space_failure_emits_receipts_for_all_views(tmp_path: Path) -> None:
    views = _prepare_views(tmp_path)
    receipts = tmp_path / "receipts.jsonl"
    create_calls = 0

    def runner(command: tuple[str, ...]) -> CommandResult:
        nonlocal create_calls
        if command == ("mantis", "--version"):
            return CommandResult(0, "mantis 3.7.0\n", "")
        create_calls += 1
        return CommandResult(1, "", "creation failed")

    result = publish_mantis.run(
        views,
        receipts,
        publish=True,
        producing_run_id="publisher-test",
        space_mode="new",
        space_name="Fixture space",
        created_at=CREATED_AT,
        runner=runner,
    )

    payloads = [json.loads(line) for line in receipts.read_text().splitlines()]
    assert len(payloads) == 3
    assert payloads[0]["error"]["code"] == "mantis_cli_failed"
    assert [payload["error"]["code"] for payload in payloads[1:]] == [
        "publication_dependency_failed",
        "publication_dependency_failed",
    ]
    assert create_calls == 1
    assert result.row_counts["failed_publications"] == 3


def test_invalid_profile_aborts_batch_before_any_remote_call(tmp_path: Path) -> None:
    views = _prepare_views(tmp_path)
    receipts = tmp_path / "receipts.jsonl"
    invalid_profile = views / "mantis_verified_claim_v1.profile.json"
    invalid_profile.write_text("{not json", encoding="utf-8")
    calls = []

    def runner(command: tuple[str, ...]) -> CommandResult:
        calls.append(command)
        return CommandResult(0, "", "")

    with pytest.raises(ValidationError, match="Could not read Mantis profile"):
        publish_mantis.run(
            views,
            receipts,
            publish=True,
            producing_run_id="publisher-test",
            space_mode="existing",
            space_id="space-fixture",
            created_at=CREATED_AT,
            runner=runner,
        )

    assert calls == []
    assert not receipts.exists()
