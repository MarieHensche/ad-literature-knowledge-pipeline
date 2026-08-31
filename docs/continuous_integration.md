# Continuous Integration

Status: implemented; local verification passed, hosted verification pending
Workflow: `.github/workflows/foundation-ci.yml`
Stable required-check name: `foundation-gate`

## Purpose

Foundation CI prevents later corpus, evidence, discovery, and validation work
from silently breaking the frozen baseline or the scientific contracts built in
Steps 1.1 through 1.9. It is an engineering gate, not scientific validation of
pipeline outputs.

The workflow runs for:

- every push;
- every pull request; and
- explicit manual dispatch.

Superseded runs for the same workflow and reference are cancelled.

## Test Matrix

The complete offline suite runs on `ubuntu-latest` with:

| Python | `PYTHONHASHSEED` |
| --- | --- |
| 3.11 | 101 |
| 3.12 | 1201 |

Two supported interpreters catch compatibility failures, while different fixed
hash seeds expose accidental dependence on set or dictionary iteration without
making a failed CI run irreproducible.

Each matrix job:

1. checks out the triggering revision without persisting credentials;
2. installs `requirements.txt` and CI-only `pytest`;
3. compiles `ad_lit_pipeline`, `pipeline_ui`, `scripts`, and `tests`; and
4. runs the complete test suite.

Dependency installation requires access to the Python package index. The test
phase itself runs with `AD_LIT_TEST_OFFLINE=1` and prepends `tests/offline/` to
`PYTHONPATH`. Its `sitecustomize.py` blocks outbound TCP connections in the test
process and inherited Python subprocesses. Unix-domain sockets remain available
for local runtime behavior.

The workflow supplies no OpenAI, provider, full-text-service, Mantis, or other
repository secret. External integrations remain fake or mocked. A future live
smoke test must use a different explicitly opt-in workflow and must never become
part of `foundation-gate` by accident.

## Security Boundary

Workflow-level permissions are limited to:

```yaml
permissions:
  contents: read
```

Checkout credentials are not persisted. Third-party actions are limited to the
official GitHub checkout and Python setup actions, pinned to full release commit
hashes:

- [`actions/checkout` 7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1)
- [`actions/setup-python` 7.0.0](https://github.com/actions/setup-python/releases/tag/v7.0.0)

Action upgrades must verify the official release, replace the full commit hash,
update `tests/test_ci_contract.py`, and rerun the local CI contract and complete
suite before merging.

## Stable Foundation Gate

The `foundation-gate` job depends on the complete Python matrix and succeeds
only when every matrix job succeeds. Its stable name avoids making branch
protection depend on matrix display names.

After the workflow exists on GitHub, configure the protected branch or ruleset
to require this status check:

```text
foundation-gate
```

That is a GitHub repository setting and is not changed by files in this
repository. No remote branch-protection setting is modified by Step 1.10.

## Local Equivalent

From an activated development environment, the focused contract is:

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_ci_contract.py \
  tests/test_documentation_contract.py
```

The closest local equivalent to one CI matrix job is:

```bash
PYTHONHASHSEED=101 \
python -m compileall -q ad_lit_pipeline pipeline_ui scripts tests

AD_LIT_TEST_OFFLINE=1 \
PYTHONHASHSEED=101 \
PYTHONPATH=tests/offline:. \
python -m pytest -q
```

Run the second seed separately when reproducing the Python 3.12 matrix entry.
The official hosted workflow remains the only proof that both declared Python
versions succeed on the GitHub runner.

## CI Contract Test

`tests/test_ci_contract.py` verifies:

- push, pull-request, and manual triggers;
- read-only permissions and cancellable concurrency;
- Python versions and fixed hash seeds;
- action commit pins and disabled credential persistence;
- the dependency, compilation, and complete-suite commands;
- absence of secret references; and
- actual outbound-socket failure in an inherited Python process.

The documentation link contract also checks that this file and every other local
Markdown link resolve.

## Deliberate Non-Goals

Step 1.10 does not add:

- live provider, OpenAI, full-text, or Mantis tests;
- remote publication or cleanup;
- linting, formatting, or type-checking gates;
- a new lockfile, `pyproject.toml`, or dependency-management workflow;
- deployment, packaging, releases, or generated-artifact uploads; or
- automatic modification of GitHub branch protection.

Those require separate scope decisions. CI passing means the checked-in offline
contracts and regressions pass; it does not mean a scientific gap is valid or a
live integration is healthy.
