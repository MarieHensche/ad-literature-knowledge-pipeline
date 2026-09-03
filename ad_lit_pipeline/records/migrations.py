from __future__ import annotations

import re
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from ad_lit_pipeline.core.errors import ValidationError
from ad_lit_pipeline.records.ids import record_id_prefix


MigrationTransform = Callable[[Mapping[str, Any]], Mapping[str, Any]]

_STABLE_SEMVER = re.compile(r"^(?P<major>[0-9]+)\.(?P<minor>[0-9]+)\.(?P<patch>[0-9]+)$")


def _version_tuple(version: str, *, field_name: str) -> tuple[int, int, int]:
    if not isinstance(version, str) or version != version.strip():
        raise ValidationError(
            f"Migration {field_name} must be a stable semantic version."
        )
    match = _STABLE_SEMVER.fullmatch(version)
    if match is None:
        raise ValidationError(
            f"Migration {field_name} must be a stable semantic version."
        )
    return tuple(
        int(match.group(component)) for component in ("major", "minor", "patch")
    )


@dataclass(frozen=True, kw_only=True)
class MigrationStep:
    """One explicitly reviewed, deterministic record-contract migration edge."""

    migration_id: str
    record_type: str
    from_version: str
    to_version: str
    description: str
    transform: MigrationTransform
    permits_major_change: bool


@dataclass(frozen=True, kw_only=True)
class MigrationPlan:
    """An exact migration path; an empty path is an explicit no-op."""

    record_type: str
    from_version: str
    to_version: str
    steps: tuple[MigrationStep, ...]

    @property
    def is_noop(self) -> bool:
        return not self.steps

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": self.record_type,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "is_noop": self.is_noop,
            "migration_ids": [step.migration_id for step in self.steps],
            "versions": [
                {
                    "from_version": step.from_version,
                    "to_version": step.to_version,
                }
                for step in self.steps
            ],
        }


class MigrationRegistry:
    """Instance-owned registry of explicit migrations.

    The registry deliberately plans but does not execute migrations. A future
    schema change must first add its target contract and an atomic collection
    migrator capable of rewriting dependent IDs and validating the complete
    result. Registering an edge alone can never mutate or auto-upgrade data.
    """

    def __init__(self) -> None:
        self._steps: dict[tuple[str, str, str], MigrationStep] = {}
        self._migration_ids: set[str] = set()

    def register(
        self,
        *,
        migration_id: str,
        record_type: str,
        from_version: str,
        to_version: str,
        description: str,
        transform: MigrationTransform,
        permits_major_change: bool = False,
    ) -> MigrationStep:
        """Register one forward edge without executing it."""
        if not isinstance(migration_id, str) or not migration_id.strip():
            raise ValidationError("Migration ID must be a non-empty string.")
        if migration_id != migration_id.strip():
            raise ValidationError("Migration ID must not contain surrounding whitespace.")
        if not isinstance(description, str) or not description.strip():
            raise ValidationError("Migration description must be a non-empty string.")
        if description != description.strip():
            raise ValidationError(
                "Migration description must not contain surrounding whitespace."
            )
        if not callable(transform):
            raise ValidationError("Migration transform must be callable.")
        if not isinstance(permits_major_change, bool):
            raise ValidationError("permits_major_change must be a boolean.")

        record_id_prefix(record_type)
        source = _version_tuple(from_version, field_name="from_version")
        target = _version_tuple(to_version, field_name="to_version")
        if target <= source:
            raise ValidationError(
                "Migration target version must be later than its source version."
            )
        if target[0] != source[0] and not permits_major_change:
            raise ValidationError(
                "Major-version migrations require permits_major_change=True and "
                "the documented major-change review."
            )

        key = (record_type, from_version, to_version)
        if key in self._steps:
            raise ValidationError(
                "Duplicate migration edge for "
                f"{record_type!r} {from_version!r} -> {to_version!r}."
            )
        if migration_id in self._migration_ids:
            raise ValidationError(f"Duplicate migration ID {migration_id!r}.")

        step = MigrationStep(
            migration_id=migration_id,
            record_type=record_type,
            from_version=from_version,
            to_version=to_version,
            description=description,
            transform=transform,
            permits_major_change=permits_major_change,
        )
        self._steps[key] = step
        self._migration_ids.add(migration_id)
        return step

    def list_steps(self, record_type: str | None = None) -> tuple[MigrationStep, ...]:
        """Return registered edges in deterministic order."""
        if record_type is not None:
            record_id_prefix(record_type)
        return tuple(
            sorted(
                (
                    step
                    for step in self._steps.values()
                    if record_type is None or step.record_type == record_type
                ),
                key=lambda step: (
                    step.record_type,
                    _version_tuple(step.from_version, field_name="from_version"),
                    _version_tuple(step.to_version, field_name="to_version"),
                    step.migration_id,
                ),
            )
        )

    def as_mapping(self) -> Mapping[tuple[str, str, str], MigrationStep]:
        """Expose an immutable snapshot, not the mutable internal registry."""
        return MappingProxyType(dict(self._steps))

    def plan(
        self,
        record_type: str,
        from_version: str,
        to_version: str,
    ) -> MigrationPlan:
        """Find the shortest deterministic explicit path between exact versions."""
        record_id_prefix(record_type)
        source = _version_tuple(from_version, field_name="from_version")
        target = _version_tuple(to_version, field_name="to_version")
        if target < source:
            raise ValidationError("Schema downgrades are not supported.")
        if source == target:
            return MigrationPlan(
                record_type=record_type,
                from_version=from_version,
                to_version=to_version,
                steps=(),
            )

        by_source: dict[str, list[MigrationStep]] = {}
        for step in self.list_steps(record_type):
            by_source.setdefault(step.from_version, []).append(step)

        queue: deque[tuple[str, tuple[MigrationStep, ...]]] = deque(
            [(from_version, ())]
        )
        visited = {from_version}
        while queue:
            version, path = queue.popleft()
            for step in by_source.get(version, []):
                next_path = (*path, step)
                if step.to_version == to_version:
                    return MigrationPlan(
                        record_type=record_type,
                        from_version=from_version,
                        to_version=to_version,
                        steps=next_path,
                    )
                if step.to_version not in visited:
                    visited.add(step.to_version)
                    queue.append((step.to_version, next_path))

        raise ValidationError(
            "No explicit migration path for "
            f"{record_type!r} {from_version!r} -> {to_version!r}."
        )


def new_migration_registry() -> MigrationRegistry:
    """Return the production registry; it is empty until a real schema changes."""
    return MigrationRegistry()
