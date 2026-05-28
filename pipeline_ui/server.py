from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import shlex
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import yaml

from ad_lit_pipeline.cli.run_collection import generated_topic_contract_path
from ad_lit_pipeline.cli.run_pipeline import SUPPORTED_PAPERS_FORMATS
from ad_lit_pipeline.core.registry import (
    COLLECTION_PIPELINE,
    COLLECTION_WITH_CONTRACT_PIPELINE,
    CONTRACT_BOOTSTRAP_PIPELINE,
    MAIN_PIPELINE,
)


ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).resolve().parent / "static"

COLLECTION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")
SAFE_CONTRACT_DIRS = (Path("configs/topics"), Path("data/collection_plans"))


class UiError(ValueError):
    """User-facing API error."""


@dataclass
class CommandSpec:
    label: str
    command: list[str]
    run_id: str
    manifest_path: str


@dataclass
class Job:
    id: str
    commands: list[CommandSpec]
    log_path: Path
    status: str = "queued"
    created_at: str = field(default_factory=lambda: utc_now())
    started_at: str | None = None
    ended_at: str | None = None
    current_index: int = 0
    return_codes: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    pid: int | None = None


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def workspace_root() -> Path:
    return ROOT


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def resolve_workspace_path(value: str, root: Path = ROOT) -> Path:
    if not value:
        raise UiError("Path is required.")

    root = root.resolve()
    raw_path = Path(value).expanduser()
    candidate = raw_path if raw_path.is_absolute() else root / raw_path
    resolved = candidate.resolve(strict=False)
    if not is_relative_to(resolved, root):
        raise UiError(f"Path leaves the workspace: {value}")
    return resolved


def relative_to_root(path: Path, root: Path = ROOT) -> str:
    return path.resolve(strict=False).relative_to(root.resolve()).as_posix()


def ensure_contract_write_path(path: Path, root: Path = ROOT) -> None:
    relative = Path(relative_to_root(path, root))
    allowed = any(
        relative == base or is_relative_to(relative, base)
        for base in SAFE_CONTRACT_DIRS
    )
    if not allowed:
        allowed_dirs = ", ".join(base.as_posix() for base in SAFE_CONTRACT_DIRS)
        raise UiError(f"Contracts can only be saved under {allowed_dirs}.")
    if path.suffix.lower() not in {".yaml", ".yml"}:
        raise UiError("Contract files must end with .yaml or .yml.")


def validate_collection(value: str) -> str:
    value = value.strip()
    if not COLLECTION_RE.match(value):
        raise UiError(
            "Collection names may contain letters, numbers, underscores, dots, "
            "and hyphens, and must start with a letter or number."
        )
    return value


def validate_run_id(value: str | None, prefix: str) -> str:
    if not value:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return f"ui-{prefix}-{stamp}-{uuid4().hex[:6]}"
    value = value.strip()
    if not RUN_ID_RE.match(value):
        raise UiError(
            "Run ids may contain letters, numbers, underscores, dots, colons, "
            "and hyphens, and must not contain path separators."
        )
    return value


def require_text(payload: dict[str, Any], key: str, label: str | None = None) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise UiError(f"{label or key} is required.")
    return value.strip()


def optional_text(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def optional_int(payload: dict[str, Any], key: str, default: int) -> int:
    value = payload.get(key, default)
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise UiError(f"{key} must be a number.") from error
    if parsed < 1:
        raise UiError(f"{key} must be at least 1.")
    return parsed


def add_step_options(command: list[str], payload: dict[str, Any]) -> None:
    only_step = optional_text(payload, "onlyStep")
    from_step = optional_text(payload, "fromStep")
    if only_step and from_step:
        raise UiError("Choose either an only-step or a from-step value, not both.")
    if only_step:
        command.extend(["--only-step", only_step])
    if from_step:
        command.extend(["--from-step", from_step])
    if payload.get("dryRun"):
        command.append("--dry-run")
    if payload.get("resume"):
        command.append("--resume")
    trace_dir = optional_text(payload, "traceDir")
    if trace_dir:
        command.extend(["--trace-dir", relative_to_root(resolve_workspace_path(trace_dir))])


def collection_step_names(
    generate_contract: bool,
    contract_bootstrap_only: bool,
) -> list[str]:
    if contract_bootstrap_only:
        return CONTRACT_BOOTSTRAP_PIPELINE
    if generate_contract:
        return COLLECTION_WITH_CONTRACT_PIPELINE
    return COLLECTION_PIPELINE


def with_valid_collection_step_options(
    payload: dict[str, Any],
    generate_contract: bool,
    contract_bootstrap_only: bool,
) -> dict[str, Any]:
    normalized = dict(payload)
    allowed_steps = set(collection_step_names(generate_contract, contract_bootstrap_only))
    for key in ("onlyStep", "fromStep"):
        value = optional_text(normalized, key)
        if value and value not in allowed_steps:
            normalized[key] = ""
    return normalized


def build_main_command(payload: dict[str, Any], root: Path = ROOT) -> CommandSpec:
    collection = validate_collection(require_text(payload, "collection", "collection"))
    papers = relative_to_root(
        resolve_workspace_path(require_text(payload, "papers", "paper input"), root),
        root,
    )
    topic_contract = relative_to_root(
        resolve_workspace_path(require_text(payload, "topicContract", "topic contract"), root),
        root,
    )
    run_id = validate_run_id(optional_text(payload, "runId"), "main")
    model = optional_text(payload, "model")

    command = [
        sys.executable,
        "scripts/run_pipeline.py",
        "run",
        "--papers",
        papers,
        "--topic-contract",
        topic_contract,
        "--collection",
        collection,
        "--run-id",
        run_id,
    ]
    if model:
        command.extend(["--model", model])
    add_step_options(command, payload)
    return CommandSpec(
        label="Tag papers",
        command=command,
        run_id=run_id,
        manifest_path=f"runs/{run_id}/manifest.json",
    )


def build_collection_command(payload: dict[str, Any], root: Path = ROOT) -> CommandSpec:
    collection = validate_collection(require_text(payload, "collection", "collection"))
    topic = optional_text(payload, "topic")
    max_results = optional_int(payload, "maxResults", 25)
    max_review_overviews = optional_int(payload, "maxReviewOverviews", 5)
    model = optional_text(payload, "model") or "gpt-4o-mini"
    run_id = validate_run_id(optional_text(payload, "runId"), "collection")
    topic_contract = optional_text(payload, "topicContract")
    generate_contract = bool(payload.get("generateTopicContract")) or not topic_contract
    contract_bootstrap_only = bool(payload.get("contractBootstrapOnly"))
    if generate_contract and not topic:
        raise UiError("topic is required when generating a topic contract.")

    command = [
        sys.executable,
        "scripts/run_collection.py",
        "run",
        "--collection",
        collection,
        "--max-results",
        str(max_results),
        "--model",
        model,
        "--run-id",
        run_id,
    ]
    if topic:
        command.extend(["--topic", topic])

    if topic_contract:
        command.extend(
            [
                "--topic-contract",
                relative_to_root(resolve_workspace_path(topic_contract, root), root),
            ]
        )

    if generate_contract:
        command.append("--generate-topic-contract")
        command.extend(["--max-review-overviews", str(max_review_overviews)])
        base_contract = optional_text(payload, "baseContract")
        if base_contract:
            command.extend(
                [
                    "--base-contract",
                    relative_to_root(resolve_workspace_path(base_contract, root), root),
                ]
            )
        if payload.get("overwriteTopicContract"):
            command.append("--overwrite-topic-contract")
    if contract_bootstrap_only:
        command.append("--contract-bootstrap-only")

    payload = with_valid_collection_step_options(
        payload,
        generate_contract,
        contract_bootstrap_only,
    )
    add_step_options(command, payload)
    label = "Create contract" if contract_bootstrap_only else "Collect papers"
    return CommandSpec(
        label=label,
        command=command,
        run_id=run_id,
        manifest_path=f"runs/{run_id}/manifest.json",
    )


def generated_contract_relative_path(collection: str) -> str:
    return generated_topic_contract_path(collection).as_posix()


def collection_papers_relative_path(collection: str) -> str:
    return (Path("data") / "raw" / f"{collection}_papers.csv").as_posix()


def build_job_commands(payload: dict[str, Any], root: Path = ROOT) -> list[CommandSpec]:
    workflow = require_text(payload, "workflow", "workflow")
    if workflow == "main":
        return [build_main_command(payload, root)]

    if workflow == "collection":
        collection = validate_collection(require_text(payload, "collection", "collection"))
        commands = [build_collection_command(payload, root)]
        if payload.get("runMainAfterCollection"):
            topic_contract = optional_text(payload, "topicContract")
            if not topic_contract:
                topic_contract = generated_contract_relative_path(collection)
            main_payload = dict(payload)
            main_payload["workflow"] = "main"
            main_payload["papers"] = collection_papers_relative_path(collection)
            main_payload["topicContract"] = topic_contract
            main_payload["runId"] = validate_run_id(None, "main")
            main_payload.pop("onlyStep", None)
            main_payload.pop("fromStep", None)
            commands.append(build_main_command(main_payload, root))
        return commands

    if workflow == "contract":
        contract_payload = dict(payload)
        contract_payload["workflow"] = "collection"
        contract_payload["generateTopicContract"] = True
        contract_payload["contractBootstrapOnly"] = True
        contract_payload["onlyStep"] = ""
        contract_payload["fromStep"] = ""
        return [build_collection_command(contract_payload, root)]

    raise UiError(f"Unknown workflow: {workflow}")


def path_summary(path: Path, root: Path = ROOT) -> dict[str, Any]:
    return {
        "path": relative_to_root(path, root),
        "name": path.name,
        "exists": path.exists(),
        "size": path.stat().st_size if path.exists() and path.is_file() else None,
        "modifiedAt": (
            datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
            if path.exists()
            else None
        ),
    }


def list_matching_files(root: Path, patterns: list[str]) -> list[dict[str, Any]]:
    files: dict[str, Path] = {}
    for pattern in patterns:
        for path in root.glob(pattern):
            if path.is_file():
                files[relative_to_root(path, root)] = path
    return [path_summary(path, root) for _, path in sorted(files.items())]


def manifest_summary(path: Path, root: Path = ROOT) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        payload = {}

    steps = payload.get("steps") if isinstance(payload.get("steps"), list) else []
    return {
        "path": relative_to_root(path, root),
        "runId": payload.get("run_id") or path.parent.name,
        "collection": payload.get("collection"),
        "pipelineName": payload.get("pipeline_name"),
        "status": payload.get("status"),
        "model": payload.get("model"),
        "startedAt": payload.get("started_at"),
        "endedAt": payload.get("ended_at"),
        "failedStep": payload.get("failed_step"),
        "stepCount": len(steps),
        "modifiedAt": datetime.fromtimestamp(
            path.stat().st_mtime,
            timezone.utc,
        ).isoformat(),
    }


def list_manifests(root: Path = ROOT) -> list[dict[str, Any]]:
    manifests = [
        manifest_summary(path, root)
        for path in root.glob("runs/*/manifest.json")
        if path.is_file()
    ]
    return sorted(manifests, key=lambda item: item.get("modifiedAt") or "", reverse=True)


def app_config(root: Path = ROOT) -> dict[str, Any]:
    paper_patterns = [f"data/raw/*{suffix}" for suffix in SUPPORTED_PAPERS_FORMATS]
    return {
        "workspace": str(root),
        "contracts": list_matching_files(
            root,
            [
                "configs/topics/*.yaml",
                "configs/topics/*.yml",
                "data/collection_plans/*.yaml",
                "data/collection_plans/*.yml",
            ],
        ),
        "paperInputs": list_matching_files(root, paper_patterns),
        "manifests": list_manifests(root),
        "steps": {
            "main": MAIN_PIPELINE,
            "collection": COLLECTION_PIPELINE,
            "collectionWithContract": COLLECTION_WITH_CONTRACT_PIPELINE,
        },
        "defaults": {
            "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            "baseContract": "configs/topics/topic_contract_template.yaml",
            "maxResults": 25,
            "maxReviewOverviews": 5,
        },
    }


def read_text_file(relative_path: str, root: Path = ROOT) -> dict[str, Any]:
    path = resolve_workspace_path(relative_path, root)
    if not path.exists() or not path.is_file():
        raise UiError(f"File does not exist: {relative_path}")
    if path.stat().st_size > 2_000_000:
        raise UiError("File is too large to preview in the UI.")
    return {
        **path_summary(path, root),
        "content": path.read_text(encoding="utf-8"),
    }


def save_contract(payload: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    relative_path = require_text(payload, "path", "contract path")
    content = require_text(payload, "content", "contract content")
    path = resolve_workspace_path(relative_path, root)
    ensure_contract_write_path(path, root)
    try:
        yaml.safe_load(content)
    except yaml.YAMLError as error:
        raise UiError(f"YAML could not be parsed: {error}") from error
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return read_text_file(relative_to_root(path, root), root)


def read_log_tail(path: Path, limit: int = 40000) -> str:
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8", errors="replace")
    if len(content) <= limit:
        return content
    return content[-limit:]


def job_payload(job: Job, root: Path = ROOT) -> dict[str, Any]:
    return {
        "id": job.id,
        "status": job.status,
        "createdAt": job.created_at,
        "startedAt": job.started_at,
        "endedAt": job.ended_at,
        "currentIndex": job.current_index,
        "pid": job.pid,
        "returnCodes": job.return_codes,
        "error": job.error,
        "logPath": relative_to_root(job.log_path, root),
        "log": read_log_tail(job.log_path),
        "commands": [
            {
                "label": command.label,
                "runId": command.run_id,
                "manifestPath": command.manifest_path,
                "command": shlex.join(command.command),
            }
            for command in job.commands
        ],
    }


def run_job(job: Job, root: Path = ROOT) -> None:
    with JOBS_LOCK:
        job.status = "running"
        job.started_at = utc_now()

    try:
        job.log_path.parent.mkdir(parents=True, exist_ok=True)
        with job.log_path.open("a", encoding="utf-8") as log_handle:
            for index, command in enumerate(job.commands):
                with JOBS_LOCK:
                    job.current_index = index
                log_handle.write(f"\n$ {shlex.join(command.command)}\n")
                log_handle.flush()
                process = subprocess.Popen(
                    command.command,
                    cwd=root,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                with JOBS_LOCK:
                    job.pid = process.pid
                return_code = process.wait()
                with JOBS_LOCK:
                    job.return_codes[command.label] = return_code
                    job.pid = None
                log_handle.write(f"\n[{command.label} exited with {return_code}]\n")
                log_handle.flush()
                if return_code != 0:
                    raise UiError(f"{command.label} failed with exit code {return_code}.")
        with JOBS_LOCK:
            job.status = "succeeded"
            job.ended_at = utc_now()
    except Exception as error:
        with JOBS_LOCK:
            job.status = "failed"
            job.error = str(error)
            job.ended_at = utc_now()


def start_job(payload: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    commands = build_job_commands(payload, root)
    first_run_id = commands[0].run_id
    log_path = root / "runs" / first_run_id / "ui_process.log"
    job = Job(id=uuid4().hex[:12], commands=commands, log_path=log_path)
    with JOBS_LOCK:
        JOBS[job.id] = job
    thread = threading.Thread(target=run_job, args=(job, root), daemon=True)
    thread.start()
    return job_payload(job, root)


class PipelineUiHandler(BaseHTTPRequestHandler):
    server_version = "PipelineUI/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def send_error_json(self, message: str, status: HTTPStatus) -> None:
        self.send_json({"error": message}, status)

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError as error:
            raise UiError(f"Invalid JSON body: {error}") from error
        if not isinstance(payload, dict):
            raise UiError("JSON body must be an object.")
        return payload

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path.startswith("/api/"):
                self.handle_api_get(parsed.path, parse_qs(parsed.query))
            else:
                self.serve_static(parsed.path)
        except UiError as error:
            self.send_error_json(str(error), HTTPStatus.BAD_REQUEST)
        except FileNotFoundError:
            self.send_error_json("Not found.", HTTPStatus.NOT_FOUND)
        except Exception as error:
            self.send_error_json(str(error), HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self.read_json_body()
            if parsed.path == "/api/contracts/save":
                self.send_json(save_contract(payload))
            elif parsed.path == "/api/runs/start":
                self.send_json(start_job(payload), HTTPStatus.ACCEPTED)
            else:
                self.send_error_json("Not found.", HTTPStatus.NOT_FOUND)
        except UiError as error:
            self.send_error_json(str(error), HTTPStatus.BAD_REQUEST)
        except Exception as error:
            self.send_error_json(str(error), HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_api_get(self, path: str, query: dict[str, list[str]]) -> None:
        if path == "/api/config":
            self.send_json(app_config())
            return

        if path == "/api/files":
            target = first_query_value(query, "path")
            self.send_json(read_text_file(target))
            return

        if path == "/api/manifests":
            self.send_json({"manifests": list_manifests()})
            return

        if path == "/api/jobs":
            with JOBS_LOCK:
                jobs = [job_payload(job) for job in JOBS.values()]
            self.send_json(
                {
                    "jobs": sorted(
                        jobs,
                        key=lambda item: item["createdAt"],
                        reverse=True,
                    )
                }
            )
            return

        if path.startswith("/api/jobs/"):
            job_id = path.removeprefix("/api/jobs/")
            with JOBS_LOCK:
                job = JOBS.get(job_id)
            if job is None:
                raise FileNotFoundError(job_id)
            self.send_json(job_payload(job))
            return

        if path == "/api/suggested-contract":
            collection = validate_collection(first_query_value(query, "collection"))
            self.send_json({"path": generated_contract_relative_path(collection)})
            return

        self.send_error_json("Not found.", HTTPStatus.NOT_FOUND)

    def serve_static(self, request_path: str) -> None:
        if request_path in {"", "/"}:
            request_path = "/index.html"
        relative = Path(request_path.lstrip("/"))
        path = (STATIC_DIR / relative).resolve(strict=False)
        if (
            not is_relative_to(path, STATIC_DIR.resolve())
            or not path.exists()
            or not path.is_file()
        ):
            raise FileNotFoundError(request_path)
        content = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix == ".js":
            content_type = "text/javascript"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def first_query_value(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key)
    if not values or not values[0]:
        raise UiError(f"Missing query parameter: {key}")
    return values[0]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local pipeline UI.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    server = ThreadingHTTPServer((args.host, args.port), PipelineUiHandler)
    print(f"Pipeline UI: http://{args.host}:{args.port}")
    print(f"Workspace: {ROOT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Pipeline UI.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
