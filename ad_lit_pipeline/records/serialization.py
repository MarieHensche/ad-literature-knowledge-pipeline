from __future__ import annotations

import json
import types
from collections.abc import Iterable, Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, TypeVar, Union, get_args, get_origin, get_type_hints

from ad_lit_pipeline.core.errors import ValidationError
from ad_lit_pipeline.records.models import RECORD_MODELS, RecordEnvelope


RecordT = TypeVar("RecordT", bound=RecordEnvelope)


def _context(path: str | None, detail: str) -> str:
    return f"{path}: {detail}" if path else detail


def _json_value(value: Any, *, field_name: str | None = None) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, str) and field_name is not None and field_name.endswith("_at"):
        from ad_lit_pipeline.records.validation import normalize_utc_timestamp

        return normalize_utc_timestamp(value, context=field_name)
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        return value
    if is_dataclass(value) and not isinstance(value, type):
        result: dict[str, Any] = {}
        for field in fields(value):
            result[field.name] = _json_value(
                getattr(value, field.name),
                field_name=field.name,
            )
        return result
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item, field_name=str(key))
            for key, item in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_json_value(item, field_name=field_name) for item in value]
    raise ValidationError(
        f"Record value for {field_name or '<value>'} has unsupported type "
        f"{type(value).__name__}."
    )


def _decode_json_value(value: Any, *, path: str) -> Any:
    if value is None or isinstance(value, str | bool | int | float):
        return value
    if isinstance(value, list):
        return tuple(
            _decode_json_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        )
    if isinstance(value, Mapping):
        decoded: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValidationError(_context(path, "object keys must be strings"))
            decoded[key] = _decode_json_value(item, path=f"{path}.{key}")
        return MappingProxyType(decoded)
    raise ValidationError(
        _context(path, f"must be JSON-compatible, got {type(value).__name__}")
    )


def _decode_dataclass(model_type: type[Any], payload: Any, *, path: str) -> Any:
    if not isinstance(payload, Mapping):
        raise ValidationError(_context(path, "must be an object"))

    model_fields = fields(model_type)
    expected = {field.name for field in model_fields}
    actual = set(payload)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing:
        raise ValidationError(_context(path, f"missing required fields: {missing}"))
    if unknown:
        raise ValidationError(_context(path, f"contains unknown fields: {unknown}"))

    hints = get_type_hints(model_type)
    decoded: dict[str, Any] = {}
    for field in model_fields:
        value = _decode_value(
            payload[field.name],
            hints[field.name],
            path=f"{path}.{field.name}",
        )
        if isinstance(value, str) and field.name.endswith("_at"):
            from ad_lit_pipeline.records.validation import normalize_utc_timestamp

            value = normalize_utc_timestamp(
                value,
                context=f"{path}.{field.name}",
            )
        decoded[field.name] = value
    try:
        return model_type(**decoded)
    except (TypeError, ValueError) as exc:
        raise ValidationError(_context(path, f"could not construct record: {exc}")) from exc


def _decode_union(value: Any, args: tuple[Any, ...], *, path: str) -> Any:
    if value is None and type(None) in args:
        return None
    errors: list[str] = []
    for member in args:
        if member is type(None):
            continue
        try:
            return _decode_value(value, member, path=path)
        except ValidationError as exc:
            errors.append(str(exc))
    raise ValidationError(_context(path, "does not match its declared union type"))


def _decode_value(value: Any, annotation: Any, *, path: str) -> Any:
    if annotation in (Any, object):
        return _decode_json_value(value, path=path)

    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin in (Union, types.UnionType):
        return _decode_union(value, args, path=path)

    if isinstance(annotation, type) and issubclass(annotation, Enum):
        if not isinstance(value, str):
            raise ValidationError(_context(path, "must be a string enum value"))
        try:
            return annotation(value)
        except ValueError as exc:
            allowed = [item.value for item in annotation]
            raise ValidationError(
                _context(path, f"must be one of {allowed}, got {value!r}")
            ) from exc

    if isinstance(annotation, type) and is_dataclass(annotation):
        return _decode_dataclass(annotation, value, path=path)

    if origin is tuple:
        if not isinstance(value, list):
            raise ValidationError(_context(path, "must be an array"))
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(
                _decode_value(item, args[0], path=f"{path}[{index}]")
                for index, item in enumerate(value)
            )
        if len(args) != len(value):
            raise ValidationError(
                _context(path, f"must contain exactly {len(args)} items")
            )
        return tuple(
            _decode_value(item, item_type, path=f"{path}[{index}]")
            for index, (item, item_type) in enumerate(zip(value, args, strict=True))
        )

    if origin in (dict, Mapping):
        if not isinstance(value, Mapping):
            raise ValidationError(_context(path, "must be an object"))
        key_type, value_type = args if args else (str, Any)
        if key_type is not str:
            raise ValidationError(
                _context(path, "record mappings must use string keys")
            )
        decoded: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValidationError(_context(path, "object keys must be strings"))
            decoded[key] = _decode_value(
                item,
                value_type,
                path=f"{path}.{key}",
            )
        return MappingProxyType(decoded)

    if annotation is str:
        if not isinstance(value, str):
            raise ValidationError(_context(path, "must be a string"))
        return value
    if annotation is bool:
        if not isinstance(value, bool):
            raise ValidationError(_context(path, "must be a boolean"))
        return value
    if annotation is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError(_context(path, "must be an integer"))
        return value
    if annotation is float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValidationError(_context(path, "must be a number"))
        return float(value)

    raise ValidationError(
        _context(path, f"uses unsupported annotation {annotation!r}")
    )


def record_to_dict(record: RecordEnvelope, *, validate: bool = True) -> dict[str, Any]:
    """Serialize one immutable versioned record to a JSON-compatible object."""
    if not isinstance(record, RecordEnvelope):
        raise ValidationError("Expected a versioned RecordEnvelope instance.")
    if validate:
        from ad_lit_pipeline.records.validation import validate_record

        validate_record(record)
    payload = {"record_type": record.RECORD_TYPE}
    for field in fields(record):
        payload[field.name] = _json_value(
            getattr(record, field.name),
            field_name=field.name,
        )
    return payload


def record_from_dict(
    payload: Mapping[str, Any],
    *,
    validate: bool = True,
) -> RecordEnvelope:
    """Parse one strict versioned record object into its frozen model."""
    if not isinstance(payload, Mapping):
        raise ValidationError("Versioned record payload must be an object.")
    record_type = payload.get("record_type")
    if not isinstance(record_type, str) or not record_type:
        raise ValidationError("Versioned record requires a non-empty record_type.")
    model_type = RECORD_MODELS.get(record_type)
    if model_type is None:
        raise ValidationError(f"Unsupported record_type {record_type!r}.")

    body = dict(payload)
    body.pop("record_type")
    record = _decode_dataclass(model_type, body, path=record_type)
    if validate:
        from ad_lit_pipeline.records.validation import validate_record

        validate_record(record)
    return record


def iter_record_jsonl(path: Path, *, validate: bool = True) -> Iterable[RecordEnvelope]:
    """Stream strict versioned records from a JSONL collection."""
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValidationError(
                    f"Invalid JSON in {path}:{line_number}: {exc.msg}"
                ) from exc
            try:
                yield record_from_dict(payload, validate=validate)
            except ValidationError as exc:
                raise ValidationError(
                    f"Invalid versioned record in {path}:{line_number}: {exc}"
                ) from exc


def read_record_jsonl(path: Path, *, validate: bool = True) -> tuple[RecordEnvelope, ...]:
    """Read a complete JSONL collection while retaining immutable ordering."""
    return tuple(iter_record_jsonl(path, validate=validate))


def write_record_jsonl(
    path: Path,
    records: Iterable[RecordEnvelope],
    *,
    validate: bool = True,
) -> None:
    """Write versioned records as deterministic compact JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            payload = record_to_dict(record, validate=validate)
            handle.write(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                )
            )
            handle.write("\n")
