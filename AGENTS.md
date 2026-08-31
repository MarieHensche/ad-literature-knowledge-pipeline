# Codex Entry Point

# Agent Instructions

Read this file before coding in this branch.

This repository is a domain-adaptable research pipeline, with an Alzheimer
default topic contract, for turning literature metadata into structured
knowledge tags and Mantis-ready outputs. The project has already been
refactored: `scripts/` should remain a compatibility and CLI layer, while
reusable behavior belongs in `ad_lit_pipeline/`.

## Core Rules

- Preserve existing CLI behavior unless the task explicitly changes it.
- Keep `scripts/` thin. Do not add business logic there if it belongs in the
  package.
- Put each behavior in one obvious package module.
- Keep topic-specific research logic in topic contracts, not hard-coded Python
  constants or prompt strings.
- Preserve input columns unless a step explicitly documents a narrower output
  contract.
- Add or update focused tests when behavior changes.
- Do not introduce unrelated refactors while solving a requested task.

## Current Structure

```text
ad_lit_pipeline/
  cli/          Orchestrated command-line workflows
  core/         Artifacts, manifests, runner helpers, step specs
  io/           CSV, JSON, JSONL, YAML, and path helpers
  llm/          Shared LLM clients, schemas, and trace writing
  prompts/      Prompt rendering and Markdown templates
  providers/    Candidate source integrations
  steps/        Pipeline step implementations
  topics/       Topic contract loading and validation
scripts/        Compatibility wrappers and direct step CLIs
configs/topics/ Topic contracts
```

## Placement Rules

| Kind of code | Location |
| --- | --- |
| Pipeline orchestration | `ad_lit_pipeline/cli/` |
| Script compatibility wrappers | `scripts/` |
| Pipeline step behavior | `ad_lit_pipeline/steps/<area>/` |
| Topic loading and validation | `ad_lit_pipeline/topics/` |
| Prompt rendering | `ad_lit_pipeline/prompts/` |
| Prompt templates | `ad_lit_pipeline/prompts/templates/` |
| OpenAI wrapper code | `ad_lit_pipeline/llm/` |
| Provider API logic | `ad_lit_pipeline/providers/` |
| CSV/JSON/YAML helpers | `ad_lit_pipeline/io/` |
| Run manifests and artifact paths | `ad_lit_pipeline/core/` |
| User-facing technical docs | `docs/technical_summary.md` |

## Step Pattern

Each pipeline task should expose a `STEP` and a `run(...)` function.

```python
STEP = StepSpec(
    name="normalize_metadata",
    inputs=["raw_papers_csv"],
    outputs=["normalized_papers_csv"],
    uses_llm=False,
)
```

Prefer pure helpers for transforms and keep side effects at the edge:

- read inputs near the start of `run(...)`
- write outputs near the end
- return `StepResult` with inputs, outputs, row counts, warnings, traces, and
  metadata

## Topic Contracts

Do not add new early-detection constants directly into step code. Use the topic
contract for:

- research topic title and description
- include and exclude criteria
- rule-based screening terms
- candidate-screening policy
- tagging categories and allowed values
- fallback policy
- enabled providers

The default contract is:

```text
configs/topics/early_detection_ad.yaml
```

`--tagging-config` still exists for legacy runs, but new work should prefer
`--topic-contract`.

## Prompt And LLM Rules

- Prompt templates live in `ad_lit_pipeline/prompts/templates/`.
- Render prompts from templates plus topic contracts and per-step payloads.
- Route OpenAI calls through `ad_lit_pipeline/llm/client.py`.
- Keep response schemas in `ad_lit_pipeline/llm/schemas.py` or near the owning
  step when the schema is truly step-specific.
- Validate parsed JSON semantically after schema parsing.
- Use fake or mocked clients in tests. Unit tests must not require live OpenAI
  calls.
- Preserve or add trace support for LLM steps.

## Provider Rules

Provider-specific request, filter, and response logic belongs in
`ad_lit_pipeline/providers/`.

The planner should only receive providers enabled by the topic contract.
`fetch_candidates` must reject unsupported providers before network calls.
OpenAlex is currently the only implemented provider.

## Data And Artifacts

- Use `csv.DictReader` and `csv.DictWriter` for current CSV streaming tasks.
- Preserve metadata columns when screening or enriching rows.
- Keep paper ids stable after creation.
- Keep provenance fields on collected candidates.
- Process JSONL line by line when practical.
- Avoid silently overwriting generated files outside the expected artifact paths.
- Generated run artifacts usually belong under `data/raw/`, `data/processed/`,
  or `runs/`.

## Error Handling

Raise clear errors with step names, artifact paths, paper ids, candidate ids, or
provider names when relevant.

Avoid:

- bare `except`
- silent exception swallowing
- debug prints left in code
- making debugging depend only on console output

Audit issues should be written as data when possible. LLM validation failures
should identify the paper or candidate that failed.

## Dependencies

- Runtime dependencies are in `requirements.txt`.
- Do not migrate this project to `pyproject.toml` yet.
- Do not add lockfiles or a new dependency workflow as part of routine changes.
- Do not add a runtime dependency unless the task needs it.
- Do not introduce `pandas`; if tabular processing becomes necessary, prefer
  `polars`, and only after a real need exists.
- Keep Jupyter-only packages out of runtime requirements.

## Python Style

- Use straightforward Python.
- Add type hints for public functions.
- Prefer dataclasses for simple structured records.
- Use context managers for files and resources.
- Use standard library, third-party, then local imports.
- Avoid wildcard imports, circular imports, global mutable state, commented-out
  code, and mutable default arguments.
- Keep comments focused on why something exists, not what the code plainly says.
- Keep line length near 88 characters where practical.
- Do not use emoji or emoji-like Unicode in code, logs, or docs unless a test is
  specifically about multibyte characters.

## Tests

Run focused tests for changed behavior and broader tests when touching shared
contracts or orchestration.

Useful commands:

```bash
pytest
pytest tests/test_non_llm_steps.py
pytest tests/test_cli_runner.py
pytest tests/test_llm_steps.py
```

Tests that touch external services must use fakes or mocks.

The GitHub Actions Foundation gate runs the complete suite on Python 3.11 and
3.12 with outbound sockets blocked during tests. Keep
`.github/workflows/foundation-ci.yml` and `docs/continuous_integration.md` in
sync; do not add secrets or live-service tests to `foundation-gate`.
