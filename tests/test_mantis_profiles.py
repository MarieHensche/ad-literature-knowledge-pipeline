from __future__ import annotations

from copy import deepcopy

import pytest

from ad_lit_pipeline.core.errors import ValidationError
from ad_lit_pipeline.mantis.profiles import (
    DEFAULT_PROFILE_DIRECTORY,
    ProfileContext,
    compile_profile,
    load_profile_template,
    template_sha256,
)
from ad_lit_pipeline.records import CorpusSnapshot
from tests.mantis_fixtures import mantis_records


CONTEXT_TIME = "2026-08-27T08:00:00Z"


def _snapshot() -> CorpusSnapshot:
    return next(
        record for record in mantis_records() if isinstance(record, CorpusSnapshot)
    )


@pytest.mark.parametrize("kind", ["paper", "verified_claim", "verified_gap"])
def test_profile_templates_compile_to_valid_snapshot_bound_records(kind: str) -> None:
    snapshot = _snapshot()
    template = load_profile_template(DEFAULT_PROFILE_DIRECTORY / f"{kind}_v1.yaml")

    profile = compile_profile(
        template,
        ProfileContext(
            corpus_snapshot_id=snapshot.record_id,
            producing_run_id="mantis-profile-test",
            created_at=CONTEXT_TIME,
        ),
    )

    assert profile.record_kind.value == kind
    assert profile.profile_version == "1.0.0"
    assert profile.compatibility_version == "1.0.0"
    assert profile.connection_compatibility_verified is False
    assert profile.extensions["mantis.profile_template"]["template_sha256"] == (
        template_sha256(template)
    )
    assert all(field.mantis_type.value != "Connection" for field in profile.fields)


def test_profile_compilation_is_deterministic_and_hash_freeze_covers_non_identity_fields() -> None:
    snapshot = _snapshot()
    template = load_profile_template(DEFAULT_PROFILE_DIRECTORY / "paper_v1.yaml")
    context = ProfileContext(
        corpus_snapshot_id=snapshot.record_id,
        producing_run_id="mantis-profile-test",
        created_at=CONTEXT_TIME,
    )

    first = compile_profile(template, context)
    second = compile_profile(template, context)
    changed = deepcopy(template)
    changed["semantic_text"]["strategy"] = "changed_strategy"

    assert first == second
    assert compile_profile(changed, context).record_id == first.record_id
    assert template_sha256(changed) != template_sha256(template)


def test_profile_loader_rejects_connection_and_unknown_fields(tmp_path) -> None:
    source = DEFAULT_PROFILE_DIRECTORY / "paper_v1.yaml"
    payload = source.read_text(encoding="utf-8")
    connection = tmp_path / "connection.yaml"
    connection.write_text(
        payload.replace("mantis_type: Links", "mantis_type: Connection", 1),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="cannot use Connection"):
        load_profile_template(connection)

    unknown = tmp_path / "unknown.yaml"
    unknown.write_text(payload + "unknown_setting: true\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="unknown=.*unknown_setting"):
        load_profile_template(unknown)


def test_profile_compiler_rejects_broader_scientific_eligibility() -> None:
    snapshot = _snapshot()
    template = load_profile_template(
        DEFAULT_PROFILE_DIRECTORY / "verified_gap_v1.yaml"
    )
    template["eligible_statuses"].append("proposed")

    with pytest.raises(ValidationError, match="scientific eligibility"):
        compile_profile(
            template,
            ProfileContext(
                corpus_snapshot_id=snapshot.record_id,
                producing_run_id="mantis-profile-test",
                created_at=CONTEXT_TIME,
            ),
        )
