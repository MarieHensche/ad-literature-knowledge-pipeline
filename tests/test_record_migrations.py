from __future__ import annotations

from types import MappingProxyType

import pytest

from ad_lit_pipeline.core.errors import ValidationError
from ad_lit_pipeline.records import MigrationRegistry, new_migration_registry


def _identity(payload):
    return payload


def test_production_registry_has_no_invented_migrations() -> None:
    registry = new_migration_registry()

    assert registry.list_steps() == ()
    assert registry.plan("claim", "1.0.0", "1.0.0").is_noop
    with pytest.raises(ValidationError, match="No explicit migration path"):
        registry.plan("claim", "1.0.0", "1.1.0")


def test_registry_plans_shortest_explicit_path_deterministically() -> None:
    registry = MigrationRegistry()
    first = registry.register(
        migration_id="claim-1.0.0-to-1.1.0",
        record_type="claim",
        from_version="1.0.0",
        to_version="1.1.0",
        description="Test-only first edge.",
        transform=_identity,
    )
    registry.register(
        migration_id="claim-1.1.0-to-1.2.0",
        record_type="claim",
        from_version="1.1.0",
        to_version="1.2.0",
        description="Test-only second edge.",
        transform=_identity,
    )
    direct = registry.register(
        migration_id="claim-1.0.0-to-1.2.0",
        record_type="claim",
        from_version="1.0.0",
        to_version="1.2.0",
        description="Test-only reviewed direct edge.",
        transform=_identity,
    )

    plan = registry.plan("claim", "1.0.0", "1.2.0")

    assert plan.steps == (direct,)
    assert plan.to_dict()["migration_ids"] == [direct.migration_id]
    assert registry.list_steps("claim")[0] is first


def test_registry_snapshot_is_immutable_and_not_live() -> None:
    registry = MigrationRegistry()
    registry.register(
        migration_id="claim-1.0.0-to-1.1.0",
        record_type="claim",
        from_version="1.0.0",
        to_version="1.1.0",
        description="Test-only edge.",
        transform=_identity,
    )
    snapshot = registry.as_mapping()

    assert isinstance(snapshot, MappingProxyType)
    with pytest.raises(TypeError):
        snapshot[("claim", "1.1.0", "1.2.0")] = snapshot[  # type: ignore[index]
            ("claim", "1.0.0", "1.1.0")
        ]


@pytest.mark.parametrize(
    ("from_version", "to_version", "message"),
    [
        ("1.0", "1.1.0", "stable semantic version"),
        ("1.1.0", "1.0.0", "later than"),
        ("1.0.0", "1.0.0", "later than"),
        ("1.0.0", "2.0.0", "Major-version"),
    ],
)
def test_registry_rejects_implicit_or_unsafe_edges(
    from_version: str,
    to_version: str,
    message: str,
) -> None:
    registry = MigrationRegistry()

    with pytest.raises(ValidationError, match=message):
        registry.register(
            migration_id="unsafe-edge",
            record_type="claim",
            from_version=from_version,
            to_version=to_version,
            description="Must be rejected.",
            transform=_identity,
        )


def test_major_edge_requires_explicit_review_flag() -> None:
    registry = MigrationRegistry()

    step = registry.register(
        migration_id="claim-major-reviewed",
        record_type="claim",
        from_version="1.0.0",
        to_version="2.0.0",
        description="Test-only explicitly reviewed major edge.",
        transform=_identity,
        permits_major_change=True,
    )

    assert step.permits_major_change


def test_registry_rejects_duplicate_ids_edges_and_downgrade_plans() -> None:
    registry = MigrationRegistry()
    kwargs = {
        "migration_id": "claim-edge",
        "record_type": "claim",
        "from_version": "1.0.0",
        "to_version": "1.1.0",
        "description": "Test-only edge.",
        "transform": _identity,
    }
    registry.register(**kwargs)

    with pytest.raises(ValidationError, match="Duplicate migration edge"):
        registry.register(**{**kwargs, "migration_id": "other-id"})
    with pytest.raises(ValidationError, match="Duplicate migration ID"):
        registry.register(
            **{
                **kwargs,
                "from_version": "1.1.0",
                "to_version": "1.2.0",
            }
        )
    with pytest.raises(ValidationError, match="downgrades"):
        registry.plan("claim", "1.1.0", "1.0.0")


def test_registry_rejects_unknown_record_type_and_noncallable_transform() -> None:
    registry = MigrationRegistry()

    with pytest.raises(ValidationError, match="Unsupported record type"):
        registry.plan("legacy_knowledge", "1.0.0", "1.1.0")
    with pytest.raises(ValidationError, match="must be callable"):
        registry.register(
            migration_id="claim-edge",
            record_type="claim",
            from_version="1.0.0",
            to_version="1.1.0",
            description="Invalid test edge.",
            transform=None,  # type: ignore[arg-type]
        )
