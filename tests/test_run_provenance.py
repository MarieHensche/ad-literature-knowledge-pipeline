from __future__ import annotations

import json
from pathlib import Path

import pytest

from ad_lit_pipeline.core.errors import ValidationError
from ad_lit_pipeline.core.manifest import (
    MANIFEST_SCHEMA_VERSION,
    ManifestRecorder,
    recorded_selected_steps,
    resume_step_from_manifest,
    resume_steps_from_manifest,
    validate_manifest_payload,
)
from ad_lit_pipeline.core.provenance import (
    REDACTED,
    RUN_PROVENANCE_SCHEMA_VERSION,
    build_run_provenance,
    collect_code_provenance,
    collect_environment_provenance,
    sanitize_command,
    sanitize_options,
    resume_compatibility_sha256,
)
from ad_lit_pipeline.core.step import StepResult
from ad_lit_pipeline.core.runner import run_selected_steps
from ad_lit_pipeline.providers.base import candidate_provider_dates


ROOT = Path(__file__).resolve().parents[1]


def test_command_and_options_redact_credentials_contacts_and_home_paths(
    tmp_path: Path,
) -> None:
    secret = "super-secret-value"
    email = "researcher@example.org"
    command = sanitize_command(
        [
            "run_pipeline.py",
            "--core-api-key",
            secret,
            f"--mailto={email}",
            f"https://example.org/api?token={secret}&page=1",
            f"https://pipeline:{secret}@example.org/private",
            str(Path.home() / ".cache" / "corpus"),
        ],
        tmp_path,
    )
    options = sanitize_options(
        {
            "core_api_key": secret,
            "full_text_email": email,
            "nested": {"password": secret},
            "message": f"authorization={secret}",
            "cache": str(Path.home() / ".cache" / "corpus"),
        },
        tmp_path,
    )
    serialized = json.dumps({"command": command, "options": options})

    assert secret not in serialized
    assert email not in serialized
    assert str(Path.home()) not in serialized
    assert REDACTED in serialized
    assert "$HOME/.cache/corpus" in serialized
    assert "page=1" in serialized


def test_resume_option_hash_detects_changed_redacted_values() -> None:
    first = resume_compatibility_sha256(
        {"full_text_email": "first@example.org", "resume": False}
    )
    second = resume_compatibility_sha256(
        {"full_text_email": "second@example.org", "resume": True}
    )

    assert first != second


def test_git_provenance_is_content_addressed_without_diff_or_file_names() -> None:
    code = collect_code_provenance(ROOT)
    serialized = json.dumps(code)

    assert code["status"] == "captured"
    assert len(code["commit"]) == 40
    assert code["repository_root"] == "."
    assert isinstance(code["dirty"], bool)
    assert len(code["source_state_sha256"]) == 64
    assert "tracked_diff" not in code
    assert "staged_diff" not in code
    assert "provenance.py" not in serialized


def test_environment_provenance_is_reconstructable_but_allowlisted() -> None:
    environment = collect_environment_provenance(ROOT)

    assert environment["python"]["implementation"]
    assert environment["python"]["version"]
    assert environment["platform"]["system"]
    assert environment["dependencies"] == sorted(
        environment["dependencies"],
        key=lambda item: (item["name"].lower(), item["version"]),
    )
    assert len(environment["dependency_snapshot_sha256"]) == 64
    assert environment["requirements"]["sha256"]
    assert set(environment["runtime_settings"]) == {
        "openai_timeout_seconds",
        "openai_max_retries",
    }


def test_candidate_provider_dates_preserve_retrieval_and_update_range() -> None:
    dates = candidate_provider_dates(
        [
            {
                "retrieval_date": "2026-08-27",
                "raw_record": {"updated_date": "2026-08-20T09:00:00Z"},
            },
            {
                "retrieval_date": "2026-08-26",
                "raw_record": {"updated_at": "2026-08-21T10:00:00Z"},
            },
            {"retrieval_date": None, "raw_record": {}},
        ]
    )

    assert dates == {
        "retrieval_date_earliest": "2026-08-26",
        "retrieval_date_latest": "2026-08-27",
        "provider_updated_at_earliest": "2026-08-20T09:00:00Z",
        "provider_updated_at_latest": "2026-08-21T10:00:00Z",
    }


def test_run_provenance_distinguishes_available_contracts_from_effective_inputs() -> None:
    provenance = build_run_provenance(
        project_root=ROOT,
        argv=["scripts/run_pipeline.py", "run"],
        options={"core_api_key": None},
        selected_steps=["normalize_metadata"],
        topic_contract_path=ROOT / "configs/topics/early_detection_ad.yaml",
        model="test-model",
    )

    assert provenance["schema_version"] == RUN_PROVENANCE_SCHEMA_VERSION
    assert provenance["contracts"]["topic_contract"]["status"] == "effective"
    assert provenance["contracts"]["topic_contract"]["topic_id"] == (
        "early_detection_ad"
    )
    topic_policy = provenance["contracts"]["topic_structure_policy"]
    assert topic_policy["status"] == "effective"
    assert topic_policy["policy_id"] == "topic_structure"
    assert len(topic_policy["sha256"]) == 64
    assert len(topic_policy["semantic_sha256"]) == 64
    assert provenance["contracts"]["scientific_validity"]["status"] == (
        "available_not_applied_by_legacy_pipeline"
    )
    assert provenance["contracts"]["record_contracts"]["status"] == (
        "available_not_emitted_by_legacy_pipeline"
    )
    assert provenance["contracts"]["response_schema_sources"]["file_count"] >= 2
    assert [provider["name"] for provider in provenance["providers"]] == [
        "openalex"
    ]
    assert provenance["corpus_snapshot"] == {
        "status": "not_emitted",
        "corpus_snapshot_id": None,
        "as_of": None,
        "reason": "The current legacy pipeline does not emit CorpusSnapshot records.",
    }


def test_new_manifest_is_versioned_atomic_and_attempt_scoped(tmp_path: Path) -> None:
    topic_path = tmp_path / "topic.yaml"
    topic_path.write_text("topic_id: test\n", encoding="utf-8")
    recorder = ManifestRecorder.create(
        collection="test",
        pipeline_name="main",
        runs_dir=tmp_path / "runs",
        run_id="run-1",
        topic_contract_path=topic_path,
        model="test-model",
        provenance={"schema_version": RUN_PROVENANCE_SCHEMA_VERSION},
    )

    recorder.finish(status="dry_run")
    payload = ManifestRecorder.load(recorder.manifest_path)

    assert payload["manifest_schema_version"] == MANIFEST_SCHEMA_VERSION
    assert payload["status"] == "dry_run"
    assert payload["attempts"][0]["attempt_id"] == "attempt-0001"
    assert payload["attempts"][0]["status"] == "dry_run"
    assert payload["attempts"][0]["step_start_index"] == 0
    assert payload["attempts"][0]["step_end_index"] == 0
    assert not list(recorder.run_dir.glob(".manifest.json.*.tmp"))
    validate_manifest_payload(payload, allow_legacy=False)


def test_existing_run_id_is_rejected_without_changing_manifest(tmp_path: Path) -> None:
    kwargs = {
        "collection": "test",
        "pipeline_name": "main",
        "runs_dir": tmp_path / "runs",
        "run_id": "run-1",
        "model": "test-model",
    }
    recorder = ManifestRecorder.create(**kwargs)
    recorder.finish(status="dry_run")
    before = recorder.manifest_path.read_bytes()

    with pytest.raises(ValueError, match="already exists.*--resume"):
        ManifestRecorder.create(**kwargs)

    assert recorder.manifest_path.read_bytes() == before


def test_resume_preserves_prior_steps_and_adds_attempt_provenance(
    tmp_path: Path,
) -> None:
    topic_path = tmp_path / "topic.yaml"
    topic_path.write_text("topic_id: test\n", encoding="utf-8")
    trace_path = tmp_path / "trace.json"
    trace_path.write_text('{"trace": true}\n', encoding="utf-8")
    recorder = ManifestRecorder.create(
        collection="test",
        pipeline_name="main",
        runs_dir=tmp_path / "runs",
        run_id="run-1",
        topic_contract_path=topic_path,
        model="test-model",
        provenance={"source_state": "first"},
    )
    recorder.record_step(
        StepResult(
            step_name="normalize_metadata",
            trace_paths=[trace_path],
            metadata={"api_key": "must-not-leak"},
            error="authorization=must-not-leak",
        ),
        status="failed",
    )
    recorder.finish(status="failed")
    original = ManifestRecorder.load(recorder.manifest_path)

    resumed = ManifestRecorder.create(
        collection="test",
        pipeline_name="main",
        runs_dir=tmp_path / "runs",
        run_id="run-1",
        topic_contract_path=topic_path,
        model="test-model",
        provenance={"source_state": "second"},
        resume=True,
    )

    assert resumed.payload["steps"] == original["steps"]
    assert len(resumed.payload["attempts"]) == 2
    assert resumed.payload["attempts"][1]["resume"] is True
    assert resumed.payload["attempts"][1]["provenance"] == {
        "source_state": "second"
    }
    failed_step = resumed.payload["steps"][0]
    assert failed_step["attempt_id"] == "attempt-0001"
    assert failed_step["metadata"]["api_key"] == REDACTED
    assert "must-not-leak" not in failed_step["error"]
    assert failed_step["trace_artifacts"][0]["sha256"]

    resumed.record_step(StepResult(step_name="normalize_metadata"))
    resumed.finish(status="succeeded")
    assert resume_step_from_manifest(resumed.manifest_path) is None
    final = ManifestRecorder.load(resumed.manifest_path)
    assert len(final["steps"]) == 2
    assert final["steps"][1]["attempt_id"] == "attempt-0002"


def test_resume_detects_interruption_and_continues_original_selection(
    tmp_path: Path,
) -> None:
    provenance = {
        "invocation": {
            "selected_steps": ["first", "second", "third"],
            "pipeline_steps": ["first", "second", "third"],
            "resume_compatibility_options": {"papers": "papers.csv"},
        }
    }
    recorder = ManifestRecorder.create(
        collection="test",
        pipeline_name="main",
        runs_dir=tmp_path / "runs",
        run_id="interrupted",
        model="test-model",
        provenance=provenance,
    )
    recorder.record_step(StepResult(step_name="first"))

    assert resume_step_from_manifest(recorder.manifest_path) == "second"
    assert resume_steps_from_manifest(recorder.manifest_path) == ["second", "third"]

    resumed = ManifestRecorder.create(
        collection="test",
        pipeline_name="main",
        runs_dir=tmp_path / "runs",
        run_id="interrupted",
        model="test-model",
        provenance=provenance,
        resume=True,
    )

    previous_attempt = resumed.payload["attempts"][0]
    assert previous_attempt["status"] == "interrupted"
    assert previous_attempt["ended_at"]
    assert previous_attempt["step_end_index"] == 1
    assert resumed.payload["attempts"][1]["status"] == "running"


def test_resume_can_finalize_crash_after_last_successful_step(tmp_path: Path) -> None:
    provenance = {
        "invocation": {
            "selected_steps": ["only_step"],
            "pipeline_steps": ["only_step"],
            "resume_compatibility_options": {},
        }
    }
    recorder = ManifestRecorder.create(
        collection="test",
        pipeline_name="main",
        runs_dir=tmp_path / "runs",
        run_id="finalization-crash",
        model="test-model",
        provenance=provenance,
    )
    recorder.record_step(StepResult(step_name="only_step"))
    payload = ManifestRecorder.load(recorder.manifest_path)

    assert recorded_selected_steps(payload) == ["only_step"]
    assert resume_steps_from_manifest(recorder.manifest_path) == []

    resumed = ManifestRecorder.create(
        collection="test",
        pipeline_name="main",
        runs_dir=tmp_path / "runs",
        run_id="finalization-crash",
        model="test-model",
        provenance=provenance,
        resume=True,
    )
    assert run_selected_steps([], {}, resumed) == "succeeded"
    final = ManifestRecorder.load(resumed.manifest_path)
    assert final["status"] == "succeeded"
    assert final["attempts"][0]["status"] == "interrupted"
    assert final["attempts"][1]["status"] == "succeeded"


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("pipeline_steps", ["first", "changed"], "pipeline structure"),
        (
            "resume_compatibility_options",
            {"papers": "changed.csv"},
            "effective options",
        ),
        ("resume_compatibility_sha256", "0" * 64, "effective options"),
    ],
)
def test_resume_rejects_changed_pipeline_or_effective_options(
    tmp_path: Path,
    field: str,
    replacement: object,
    message: str,
) -> None:
    provenance = {
        "invocation": {
            "selected_steps": ["first", "second"],
            "pipeline_steps": ["first", "second"],
            "resume_compatibility_options": {"papers": "papers.csv"},
            "resume_compatibility_sha256": "1" * 64,
        }
    }
    recorder = ManifestRecorder.create(
        collection="test",
        pipeline_name="main",
        runs_dir=tmp_path / "runs",
        run_id="run-1",
        model="test-model",
        provenance=provenance,
    )
    recorder.record_step(StepResult(step_name="first"))
    changed = json.loads(json.dumps(provenance))
    changed["invocation"][field] = replacement

    with pytest.raises(ValueError, match=message):
        ManifestRecorder.create(
            collection="test",
            pipeline_name="main",
            runs_dir=tmp_path / "runs",
            run_id="run-1",
            model="test-model",
            provenance=changed,
            resume=True,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("collection", "other", "collection"),
        ("pipeline_name", "collection", "pipeline_name"),
        ("model", "other-model", "model"),
    ],
)
def test_resume_rejects_incompatible_run_identity(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    topic_path = tmp_path / "topic.yaml"
    topic_path.write_text("topic_id: test\n", encoding="utf-8")
    kwargs = {
        "collection": "test",
        "pipeline_name": "main",
        "runs_dir": tmp_path / "runs",
        "run_id": "run-1",
        "topic_contract_path": topic_path,
        "model": "test-model",
    }
    recorder = ManifestRecorder.create(**kwargs)
    recorder.finish(status="failed")

    with pytest.raises(ValueError, match=message):
        ManifestRecorder.create(**{**kwargs, field: value}, resume=True)


def test_resume_rejects_changed_topic_contract(tmp_path: Path) -> None:
    topic_path = tmp_path / "topic.yaml"
    topic_path.write_text("topic_id: first\n", encoding="utf-8")
    recorder = ManifestRecorder.create(
        collection="test",
        pipeline_name="main",
        runs_dir=tmp_path / "runs",
        run_id="run-1",
        topic_contract_path=topic_path,
        model="test-model",
    )
    recorder.finish(status="failed")
    topic_path.write_text("topic_id: changed\n", encoding="utf-8")

    with pytest.raises(ValueError, match="topic contract changed"):
        ManifestRecorder.create(
            collection="test",
            pipeline_name="main",
            runs_dir=tmp_path / "runs",
            run_id="run-1",
            topic_contract_path=topic_path,
            model="test-model",
            resume=True,
        )


def test_resume_rejects_missing_recorded_topic_contract(tmp_path: Path) -> None:
    topic_path = tmp_path / "topic.yaml"
    topic_path.write_text("topic_id: first\n", encoding="utf-8")
    recorder = ManifestRecorder.create(
        collection="test",
        pipeline_name="main",
        runs_dir=tmp_path / "runs",
        run_id="run-1",
        topic_contract_path=topic_path,
        model="test-model",
    )
    recorder.finish(status="failed")
    topic_path.unlink()

    with pytest.raises(ValueError, match="topic contract is unavailable"):
        ManifestRecorder.create(
            collection="test",
            pipeline_name="main",
            runs_dir=tmp_path / "runs",
            run_id="run-1",
            topic_contract_path=topic_path,
            model="test-model",
            resume=True,
        )


def test_legacy_manifest_can_be_resumed_without_losing_history(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "legacy-run"
    run_dir.mkdir(parents=True)
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_id": "legacy-run",
                "collection": "test",
                "pipeline_name": "main",
                "status": "failed",
                "started_at": "2026-01-01T00:00:00+00:00",
                "ended_at": "2026-01-01T00:01:00+00:00",
                "topic_contract": None,
                "model": "test-model",
                "steps": [
                    {
                        "step_name": "normalize_metadata",
                        "status": "failed",
                    }
                ],
                "failed_step": "normalize_metadata",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    recorder = ManifestRecorder.create(
        collection="test",
        pipeline_name="main",
        runs_dir=tmp_path / "runs",
        run_id="legacy-run",
        topic_contract_path=None,
        model="test-model",
        provenance={"source": "resume"},
        resume=True,
    )

    assert recorder.payload["manifest_schema_version"] == MANIFEST_SCHEMA_VERSION
    assert len(recorder.payload["steps"]) == 1
    assert recorder.payload["attempts"][0]["attempt_id"] == (
        "attempt-0000-legacy"
    )
    assert recorder.payload["attempts"][1]["resume"] is True


def test_legacy_resume_uses_current_pipeline_suffix_as_fallback(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "legacy-run"
    run_dir.mkdir(parents=True)
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_id": "legacy-run",
                "collection": "test",
                "pipeline_name": "main",
                "status": "failed",
                "started_at": "2026-01-01T00:00:00+00:00",
                "topic_contract": None,
                "model": "test-model",
                "steps": [],
                "failed_step": "second",
            }
        ),
        encoding="utf-8",
    )

    assert resume_steps_from_manifest(
        manifest_path,
        fallback_steps=["second", "third"],
    ) == ["second", "third"]


def test_manifest_validator_rejects_unknown_schema() -> None:
    with pytest.raises(ValidationError, match="Unsupported manifest_schema_version"):
        validate_manifest_payload(
            {"manifest_schema_version": "2.0.0"},
            allow_legacy=False,
        )
