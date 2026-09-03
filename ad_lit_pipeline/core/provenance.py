from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ad_lit_pipeline.corpus.specification import corpus_specification_from_contract
from ad_lit_pipeline.io.yaml_io import read_yaml_object
from ad_lit_pipeline.providers.evidence import PROVIDER_EVIDENCE_SCHEMA_VERSION
from ad_lit_pipeline.records.registry import SCHEMA_VERSION
from ad_lit_pipeline.steps.collection.materialize_snapshot import (
    SNAPSHOT_INTEGRITY_SCHEMA_VERSION,
    SNAPSHOT_MATERIALIZATION_POLICY_VERSION,
)
from ad_lit_pipeline.topics.policy import (
    DEFAULT_TOPIC_STRUCTURE_POLICY_PATH,
    load_topic_structure_policy,
)


RUN_PROVENANCE_SCHEMA_VERSION = "1.0.0"
REDACTED = "<redacted>"
RESUME_TRANSIENT_OPTIONS = frozenset(
    {
        "dry_run",
        "from_step",
        "only_step",
        "resume",
        "run_id",
    }
)

_SENSITIVE_KEY = re.compile(
    r"(?:^|[_-])(?:api[_-]?key|authorization|cookie|credential|password|"
    r"secret|token)(?:$|[_-])",
    re.IGNORECASE,
)
_PRIVATE_CONTACT_KEY = re.compile(
    r"(?:^|[_-])(?:email|mailto)(?:$|[_-])",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?P<key>(?:api[_-]?key|authorization|cookie|credential|password|secret|token))"
    r"(?P<separator>\s*[:=]\s*)(?P<value>[^\s,;&]+)",
    re.IGNORECASE,
)
_SOURCE_SUFFIXES = frozenset(
    {".cfg", ".ini", ".json", ".md", ".py", ".toml", ".txt", ".yaml", ".yml"}
)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _display_path(path: Path, project_root: Path) -> str:
    candidate = path.expanduser()
    try:
        return str(candidate.resolve().relative_to(project_root.resolve())) or "."
    except (OSError, ValueError):
        text = str(candidate)
        home = str(Path.home())
        if text == home:
            return "$HOME"
        if text.startswith(home + os.sep):
            return "$HOME" + text[len(home) :]
        return text


def file_reference(path: Path, project_root: Path) -> dict[str, Any]:
    return {
        "path": _display_path(path, project_root),
        "exists": path.is_file(),
        "sha256": file_sha256(path),
    }


def directory_reference(
    path: Path,
    project_root: Path,
    *,
    suffixes: frozenset[str] | None = None,
) -> dict[str, Any]:
    files = []
    if path.is_dir():
        for candidate in sorted(item for item in path.rglob("*") if item.is_file()):
            if suffixes is not None and candidate.suffix.lower() not in suffixes:
                continue
            digest = file_sha256(candidate)
            if digest is not None:
                files.append(
                    {
                        "path": str(candidate.relative_to(path)),
                        "sha256": digest,
                    }
                )
    return {
        "path": _display_path(path, project_root),
        "exists": path.is_dir(),
        "file_count": len(files),
        "sha256": _canonical_sha256(files) if files else None,
    }


def files_reference(
    paths: Sequence[Path],
    project_root: Path,
) -> dict[str, Any]:
    files = [
        file_reference(path, project_root)
        for path in sorted(paths)
        if path.is_file()
    ]
    return {
        "file_count": len(files),
        "sha256": _canonical_sha256(files) if files else None,
        "files": files,
    }


def _run_git(project_root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(project_root), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


def _git_text(project_root: Path, *arguments: str) -> str:
    return _run_git(project_root, *arguments).decode("utf-8", errors="replace").strip()


def _untracked_source_hash(project_root: Path) -> tuple[int, str | None]:
    raw = _run_git(
        project_root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
    )
    entries = []
    for item in raw.split(b"\0"):
        if not item:
            continue
        relative = Path(item.decode("utf-8", errors="surrogateescape"))
        path = project_root / relative
        if not path.is_file() or path.suffix.lower() not in _SOURCE_SUFFIXES:
            continue
        digest = file_sha256(path)
        if digest is not None:
            entries.append({"path_sha256": _sha256_bytes(item), "sha256": digest})
    return len(entries), _canonical_sha256(entries) if entries else None


def collect_code_provenance(project_root: Path) -> dict[str, Any]:
    """Collect content-addressed Git state without storing source diffs or paths."""
    root = project_root.resolve()
    try:
        repository_root = Path(
            _git_text(root, "rev-parse", "--show-toplevel")
        ).resolve()
        commit = _git_text(repository_root, "rev-parse", "HEAD")
        branch = _git_text(repository_root, "branch", "--show-current") or None
        status = _run_git(repository_root, "status", "--porcelain=v1", "-z")
        tracked_diff = _run_git(
            repository_root,
            "diff",
            "--binary",
            "--no-ext-diff",
        )
        staged_diff = _run_git(
            repository_root,
            "diff",
            "--cached",
            "--binary",
            "--no-ext-diff",
        )
        untracked_count, untracked_hash = _untracked_source_hash(repository_root)
        state = {
            "commit": commit,
            "commit_time": _git_text(
                repository_root,
                "show",
                "-s",
                "--format=%cI",
                "HEAD",
            ),
            "branch": branch,
            "detached": branch is None,
            "dirty": bool(status),
            "status_sha256": _sha256_bytes(status),
            "tracked_diff_sha256": _sha256_bytes(tracked_diff),
            "staged_diff_sha256": _sha256_bytes(staged_diff),
            "untracked_source_file_count": untracked_count,
            "untracked_source_sha256": untracked_hash,
        }
        state["source_state_sha256"] = _canonical_sha256(state)
        return {
            "status": "captured",
            "repository_root": _display_path(repository_root, repository_root),
            **state,
        }
    except (OSError, subprocess.CalledProcessError) as exc:
        return {
            "status": "not_available",
            "reason": type(exc).__name__,
            "repository_root": _display_path(root, root),
        }


def collect_environment_provenance(project_root: Path) -> dict[str, Any]:
    packages = sorted(
        {
            (
                distribution.metadata.get("Name") or distribution.name,
                distribution.version,
            )
            for distribution in importlib.metadata.distributions()
        },
        key=lambda item: (item[0].lower(), item[1]),
    )
    package_payload = [
        {"name": name, "version": version} for name, version in packages
    ]
    requirements = file_reference(project_root / "requirements.txt", project_root)
    return {
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
            "executable_name": Path(sys.executable).name,
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "dependencies": package_payload,
        "dependency_snapshot_sha256": _canonical_sha256(package_payload),
        "requirements": requirements,
        "runtime_settings": {
            "openai_timeout_seconds": os.getenv("OPENAI_TIMEOUT_SECONDS") or None,
            "openai_max_retries": os.getenv("OPENAI_MAX_RETRIES") or None,
        },
    }


def _sanitize_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"}:
        return value
    netloc = parsed.netloc
    if parsed.username is not None or parsed.password is not None:
        hostname = parsed.hostname or ""
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        port = f":{parsed.port}" if parsed.port is not None else ""
        netloc = f"{REDACTED}@{hostname}{port}"
    query = []
    for key, item in parse_qsl(parsed.query, keep_blank_values=True):
        if _SENSITIVE_KEY.search(key) or _PRIVATE_CONTACT_KEY.search(key):
            query.append((key, REDACTED))
        else:
            query.append((key, item))
    return urlunsplit(
        (parsed.scheme, netloc, parsed.path, urlencode(query), parsed.fragment)
    )


def _sanitize_string(value: str, project_root: Path) -> str:
    sanitized = _EMAIL.sub(REDACTED, value)
    sanitized = _SENSITIVE_ASSIGNMENT.sub(
        lambda match: (
            f"{match.group('key')}{match.group('separator')}{REDACTED}"
        ),
        sanitized,
    )
    sanitized = _sanitize_url(sanitized)
    root = str(project_root.resolve())
    home = str(Path.home())
    if sanitized == root:
        return "."
    if sanitized.startswith(root + os.sep):
        return "." + sanitized[len(root) :]
    if sanitized == home:
        return "$HOME"
    if sanitized.startswith(home + os.sep):
        return "$HOME" + sanitized[len(home) :]
    return sanitized


def sanitize_value(value: Any, project_root: Path, *, key: str = "value") -> Any:
    """Return one JSON-safe value with credentials and contact data removed."""
    if _SENSITIVE_KEY.search(key) or _PRIVATE_CONTACT_KEY.search(key):
        return REDACTED if value not in (None, "") else None
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, Path):
        return _display_path(value, project_root)
    if isinstance(value, str):
        return _sanitize_string(value, project_root)
    if isinstance(value, Mapping):
        return {
            str(child_key): sanitize_value(
                child_value,
                project_root,
                key=str(child_key),
            )
            for child_key, child_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_value(item, project_root, key=key) for item in value]
    return repr(value)


def sanitize_options(options: Mapping[str, Any], project_root: Path) -> dict[str, Any]:
    """Return JSON-safe CLI options with secrets and contact data removed."""

    return {
        str(key): sanitize_value(value, project_root, key=str(key))
        for key, value in sorted(options.items(), key=lambda item: str(item[0]))
    }


def resume_compatibility_options(
    options: Mapping[str, Any],
    project_root: Path,
) -> dict[str, Any]:
    """Return effective CLI options that must remain stable across attempts."""
    return sanitize_options(
        {
            key: value
            for key, value in options.items()
            if str(key) not in RESUME_TRANSIENT_OPTIONS
        },
        project_root,
    )


def _compatibility_fingerprint_value(value: Any) -> Any:
    """Normalize option values for hashing without persisting their contents."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(key): _compatibility_fingerprint_value(child)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_compatibility_fingerprint_value(item) for item in value]
    return repr(value)


def resume_compatibility_sha256(options: Mapping[str, Any]) -> str:
    """Hash effective resume options, including values redacted in the manifest."""
    effective = {
        str(key): _compatibility_fingerprint_value(value)
        for key, value in options.items()
        if str(key) not in RESUME_TRANSIENT_OPTIONS
    }
    return _canonical_sha256(effective)


def sanitize_command(argv: Sequence[str], project_root: Path) -> list[str]:
    result = []
    redact_next = False
    for token in argv:
        if redact_next:
            result.append(REDACTED)
            redact_next = False
            continue
        if token.startswith("--"):
            option, separator, value = token.partition("=")
            key = option.removeprefix("--").replace("-", "_")
            is_private = _SENSITIVE_KEY.search(key) or _PRIVATE_CONTACT_KEY.search(key)
            if separator and is_private:
                result.append(f"{option}={REDACTED}")
                continue
            if not separator and is_private:
                result.append(option)
                redact_next = True
                continue
        result.append(_sanitize_string(token, project_root))
    return result


def _yaml_contract_reference(
    path: Path,
    project_root: Path,
    *,
    version_fields: Sequence[str],
    status: str,
) -> dict[str, Any]:
    reference = {**file_reference(path, project_root), "status": status}
    if not path.is_file():
        return reference
    try:
        payload = read_yaml_object(path)
    except (OSError, ValueError) as exc:
        reference["metadata_status"] = "invalid"
        reference["metadata_error"] = type(exc).__name__
        return reference
    reference["metadata_status"] = "captured"
    for field in version_fields:
        value = payload.get(field)
        if value is not None:
            reference[field] = value
    return reference


def _topic_contract_reference(
    path: Path | None,
    project_root: Path,
) -> tuple[dict[str, Any] | None, tuple[str, ...]]:
    if path is None:
        return None, ()
    reference = _yaml_contract_reference(
        path,
        project_root,
        version_fields=("topic_id", "schema_version", "contract_version", "version"),
        status="effective" if path.is_file() else "pending_generation",
    )
    providers: tuple[str, ...] = ()
    if path.is_file():
        try:
            payload = read_yaml_object(path)
            collection = payload.get("collection")
            if isinstance(collection, Mapping):
                allowed = collection.get("allowed_providers")
                if isinstance(allowed, list):
                    providers = tuple(
                        sorted(
                            {
                                str(provider).strip()
                                for provider in allowed
                                if str(provider).strip()
                            }
                        )
                    )
                specification = corpus_specification_from_contract(payload)
                specification_mapping = specification.semantic_mapping()
                reference["corpus_specification_status"] = (
                    "declared"
                    if "corpus_specification" in collection
                    else "compatibility_default"
                )
                reference["corpus_specification"] = specification_mapping
                reference["corpus_specification_sha256"] = _canonical_sha256(
                    specification_mapping
                )
        except (OSError, ValueError):
            pass
    return reference, providers


def _provider_references(
    provider_names: Sequence[str],
    project_root: Path,
) -> list[dict[str, Any]]:
    references = []
    for name in sorted(set(provider_names)):
        module_path = project_root / "ad_lit_pipeline" / "providers" / f"{name}.py"
        references.append(
            {
                "name": name,
                "implementation": file_reference(module_path, project_root),
                "implementation_status": (
                    "available" if module_path.is_file() else "unsupported"
                ),
            }
        )
    return references


def collect_contract_provenance(
    project_root: Path,
    topic_contract_path: Path | None,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    topic, providers = _topic_contract_reference(topic_contract_path, project_root)
    scientific_validity_path = (
        project_root / "configs" / "policies" / "scientific_validity_v1.yaml"
    )
    gap_ontology_path = (
        project_root / "configs" / "policies" / "gap_ontology_v1.yaml"
    )
    topic_structure_policy_path = DEFAULT_TOPIC_STRUCTURE_POLICY_PATH
    topic_structure_reference = _yaml_contract_reference(
        topic_structure_policy_path,
        project_root,
        version_fields=("schema_version", "policy_id", "policy_version"),
        status="effective",
    )
    try:
        topic_structure_reference["semantic_sha256"] = (
            load_topic_structure_policy(topic_structure_policy_path).sha256
        )
    except (OSError, ValueError) as exc:
        topic_structure_reference["semantic_status"] = "invalid"
        topic_structure_reference["semantic_error"] = type(exc).__name__
    contracts = {
        "topic_contract": topic,
        "topic_structure_policy": topic_structure_reference,
        "scientific_validity": _yaml_contract_reference(
            scientific_validity_path,
            project_root,
            version_fields=("schema_version", "policy_id", "policy_version"),
            status="available_not_applied_by_legacy_pipeline",
        ),
        "gap_ontology": _yaml_contract_reference(
            gap_ontology_path,
            project_root,
            version_fields=("schema_version", "ontology_id", "ontology_version"),
            status="available_not_applied_by_legacy_pipeline",
        ),
        "record_contracts": {
            **file_reference(
                project_root / "ad_lit_pipeline" / "records" / "registry.py",
                project_root,
            ),
            "schema_version": SCHEMA_VERSION,
            "status": "available_not_emitted_by_legacy_pipeline",
        },
        "provider_evidence": {
            **file_reference(
                project_root / "ad_lit_pipeline" / "providers" / "evidence.py",
                project_root,
            ),
            "schema_version": PROVIDER_EVIDENCE_SCHEMA_VERSION,
            "status": "emitted_by_provider_collection_steps",
        },
        "corpus_snapshot_materialization": {
            **file_reference(
                project_root
                / "ad_lit_pipeline"
                / "steps"
                / "collection"
                / "materialize_snapshot.py",
                project_root,
            ),
            "integrity_schema_version": SNAPSHOT_INTEGRITY_SCHEMA_VERSION,
            "policy_version": SNAPSHOT_MATERIALIZATION_POLICY_VERSION,
            "status": "emitted_by_collection_snapshot_step",
        },
        "prompt_templates": directory_reference(
            project_root / "ad_lit_pipeline" / "prompts" / "templates",
            project_root,
            suffixes=frozenset({".md"}),
        ),
        "response_schema_sources": files_reference(
            tuple(
                (project_root / "ad_lit_pipeline").rglob("*schemas.py")
            ),
            project_root,
        ),
    }
    return contracts, providers


def build_run_provenance(
    *,
    project_root: Path,
    argv: Sequence[str],
    options: Mapping[str, Any],
    selected_steps: Sequence[str],
    pipeline_steps: Sequence[str] | None = None,
    topic_contract_path: Path | None,
    model: str | None,
    corpus_snapshot_id: str | None = None,
    corpus_as_of: str | None = None,
    configured_provider_names: Sequence[str] = (),
) -> dict[str, Any]:
    root = project_root.resolve()
    contracts, providers = collect_contract_provenance(root, topic_contract_path)
    materialization_selected = "materialize_corpus_snapshot" in selected_steps
    snapshot_status = (
        "declared"
        if corpus_snapshot_id is not None
        else (
            "pending_collection_materialization"
            if materialization_selected
            else "not_emitted"
        )
    )
    return {
        "schema_version": RUN_PROVENANCE_SCHEMA_VERSION,
        "code": collect_code_provenance(root),
        "environment": collect_environment_provenance(root),
        "invocation": {
            "command": sanitize_command(argv, root),
            "working_directory": _display_path(Path.cwd(), root),
            "options": sanitize_options(options, root),
            "resume_compatibility_options": resume_compatibility_options(
                options,
                root,
            ),
            "resume_compatibility_sha256": resume_compatibility_sha256(options),
            "selected_steps": list(selected_steps),
            "pipeline_steps": list(pipeline_steps or selected_steps),
            "model": model,
        },
        "contracts": contracts,
        "providers": _provider_references(
            tuple(sorted(set(providers) | set(configured_provider_names))),
            root,
        ),
        "corpus_snapshot": {
            "status": snapshot_status,
            "corpus_snapshot_id": corpus_snapshot_id,
            "as_of": corpus_as_of,
            "reason": (
                None
                if corpus_snapshot_id is not None
                else (
                    "The selected collection workflow may emit the snapshot in "
                    "its final materialization step; no snapshot exists at run "
                    "initialization."
                    if materialization_selected
                    else "The selected workflow does not emit CorpusSnapshot records."
                )
            ),
        },
    }
