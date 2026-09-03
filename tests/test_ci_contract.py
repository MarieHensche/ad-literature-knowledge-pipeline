from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "foundation-ci.yml"
OFFLINE_IMPORT_PATH = ROOT / "tests" / "offline"
CHECKOUT_SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
SETUP_PYTHON_SHA = "5fda3b95a4ea91299a34e894583c3862153e4b97"


def load_workflow() -> dict[str, object]:
    payload = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(payload, dict)
    return payload


def test_foundation_workflow_has_safe_triggers_permissions_and_gate() -> None:
    workflow = load_workflow()
    assert set(workflow["on"]) == {"push", "pull_request", "workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"] == {
        "group": "foundation-${{ github.workflow }}-${{ github.ref }}",
        "cancel-in-progress": "true",
    }

    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    gate = jobs["foundation-gate"]
    assert gate["name"] == "foundation-gate"
    assert gate["if"] == "always()"
    assert gate["needs"] == "offline-suite"
    assert gate["timeout-minutes"] == "2"


def test_offline_matrix_pins_actions_and_runs_the_complete_suite() -> None:
    workflow = load_workflow()
    suite = workflow["jobs"]["offline-suite"]
    assert suite["runs-on"] == "ubuntu-latest"
    assert suite["timeout-minutes"] == "10"
    assert suite["strategy"]["fail-fast"] == "false"
    assert suite["strategy"]["matrix"]["include"] == [
        {"python-version": "3.11", "hash-seed": "101"},
        {"python-version": "3.12", "hash-seed": "1201"},
    ]
    assert suite["env"] == {
        "PYTHONHASHSEED": "${{ matrix.hash-seed }}",
    }

    steps = suite["steps"]
    uses = [step["uses"] for step in steps if "uses" in step]
    assert uses == [
        f"actions/checkout@{CHECKOUT_SHA}",
        f"actions/setup-python@{SETUP_PYTHON_SHA}",
    ]
    checkout = next(
        step
        for step in steps
        if step.get("uses", "").startswith("actions/checkout@")
    )
    assert checkout["with"]["persist-credentials"] == "false"

    install_step = next(
        step
        for step in steps
        if step["name"] == "Install runtime and test dependencies"
    )
    for variable in ("AD_LIT_TEST_OFFLINE", "PYTHONPATH"):
        assert variable not in install_step.get("env", {})

    test_step = next(
        step for step in steps if step["name"] == "Run complete offline suite"
    )
    assert test_step["env"] == {
        "AD_LIT_TEST_OFFLINE": "1",
        "PYTHONPATH": "tests/offline:.",
    }

    commands = "\n".join(step.get("run", "") for step in steps)
    assert "python -m pip install -r requirements.txt" in commands
    assert "python -m compileall -q" in commands
    assert "python -m pytest -q" in commands
    assert "secrets." not in WORKFLOW.read_text(encoding="utf-8")


def test_offline_guard_blocks_network_in_inherited_python_process() -> None:
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = os.pathsep.join(
        path
        for path in (str(OFFLINE_IMPORT_PATH), str(ROOT), existing_pythonpath)
        if path
    )
    environment["AD_LIT_TEST_OFFLINE"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import socket; socket.create_connection(('example.invalid', 443))",
        ],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "External network access is disabled" in result.stderr
