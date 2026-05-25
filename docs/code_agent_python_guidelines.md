# Python Code Agent Guidelines

These guidelines are for AI coding agents and contributors working on this
repository. They combine general Python quality rules with repository-specific
rules from:

- `docs/pipeline_summary.md`
- `docs/refactoring_plan.md`

They apply to both the current `scripts/` workflow and the planned
`ad_lit_pipeline/` package refactor.

## Core Principles

Write code that is clear, maintainable, testable, and efficient for the actual
pipeline workload.

"Optimized" means:

- choose appropriate algorithmic complexity for runtime and memory
- stream or batch large CSV/JSONL data instead of loading everything when that
  becomes a bottleneck
- use parallelization only where it improves throughput without making debugging
  harder
- avoid duplicate logic
- avoid adding unnecessary abstractions
- avoid adding code that is unrelated to the user's request
- preserve existing CLI behavior unless the task explicitly changes it

Prefer clarity and maintainability over cleverness. A simple, well-tested
function is better than a clever abstraction that hides pipeline behavior.

## Repository Intent

This project turns Alzheimer-related literature metadata into structured data
for Mantis.

It currently has two workflows:

1. Existing paper metadata CSV to Mantis-ready CSV.
2. Topic description to collected candidate papers, then into the main tagging
   pipeline.

The main refactoring direction is:

- scripts become thin wrappers
- reusable logic moves into `ad_lit_pipeline/`
- topic-specific behavior moves into topic contracts
- prompts move into templates
- LLM calls become traceable
- providers become modular
- each pipeline task has one obvious home

## Current And Target Structure

Current executable scripts live in `scripts/`.

Target reusable code should live under:

```text
ad_lit_pipeline/
  cli/
  core/
  io/
  llm/
  prompts/
  providers/
  steps/
  topics/
```

During migration, keep compatibility wrappers in `scripts/`. A script should
parse CLI arguments and call package code. It should not contain the main
business logic once that logic has been moved.

## Placement Rules

Use this mapping when adding or moving code:

| Kind of code | Location |
| --- | --- |
| CLI argument parsing | `scripts/` or `ad_lit_pipeline/cli/` |
| Pipeline step behavior | `ad_lit_pipeline/steps/<area>/<task>.py` |
| Topic loading and validation | `ad_lit_pipeline/topics/` |
| Prompt rendering | `ad_lit_pipeline/prompts/` |
| Prompt templates | `ad_lit_pipeline/prompts/templates/` |
| OpenAI wrapper code | `ad_lit_pipeline/llm/` |
| OpenAlex/Semantic Scholar/etc. APIs | `ad_lit_pipeline/providers/` |
| CSV/JSON/YAML helpers | `ad_lit_pipeline/io/` |
| Run manifest, context, artifacts | `ad_lit_pipeline/core/` |
| User-facing architecture docs | `docs/` |

If a change touches more than one area, keep each piece in its proper module.
For example, do not put OpenAlex HTTP code inside a tagging step.

## Step Module Pattern

Each pipeline task should have a predictable shape.

```python
from ad_lit_pipeline.core.step import StepResult, StepSpec

STEP = StepSpec(
    name="normalize_metadata",
    inputs=["raw_papers_csv"],
    outputs=["normalized_papers_csv"],
    uses_llm=False,
)


def run(context: RunContext) -> StepResult:
    """Run the step using paths and settings from context."""
    ...
```

Prefer pure helper functions inside the module:

```python
def normalize_row(row: dict[str, str], row_number: int) -> dict[str, str]:
    """Normalize one paper metadata row."""
    ...
```

Keep side effects at the edge:

- read inputs near the start of `run()`
- write outputs near the end of `run()`
- return a `StepResult` with counts, warnings, and artifact paths

## CLI Wrapper Pattern

Single-step scripts should remain usable, especially during migration.

```python
def main() -> None:
    """Parse CLI arguments and run the step."""
    args = parse_args()
    context = context_from_args(args)
    result = run(context)
    print_summary(result)
```

Avoid duplicating step logic in wrappers. If logic is needed by tests or by
another pipeline, it belongs in `ad_lit_pipeline/`.

## Topic Contract Rules

Do not add new topic-specific constants directly into step code unless this is
temporary and documented.

Topic-specific behavior should come from a topic contract:

- research topic title and description
- include criteria
- exclude criteria
- boundary rules
- rule-based include/exclude terms
- candidate-screening policy
- allowed tagging categories and values
- fallback policy
- allowed providers
- collection defaults

Examples of things that should move out of Python code and into the topic
contract:

- `early detection`, `mild cognitive impairment`, and other include terms
- `drug discovery`, `treatment`, and other exclude terms
- missing abstract means exclude
- prefer `unclear` as a fallback when allowed
- `knowledge_confidence` fallback is `very_low`
- allowed `review_status` values

The code should read the contract, validate it, and render prompts from it.

## Prompt Rules

Do not bury long prompts in Python functions once prompt templates exist.

Prompt templates should live in:

```text
ad_lit_pipeline/prompts/templates/
```

Use one template per LLM task:

```text
plan_search.md
screen_candidate.md
generate_tagging_rules.md
tag_paper.md
```

Prompt rendering should combine:

- the template
- the topic contract
- the candidate or paper payload
- allowed values
- fixed rules, when relevant

When editing prompts:

- keep policy in the topic contract when possible
- keep reusable wording in templates
- avoid duplicating the same rule across multiple templates
- update tests or fixtures that assert rendered prompt content

## LLM Call Rules

All OpenAI calls should eventually go through a shared LLM client in
`ad_lit_pipeline/llm/client.py`.

Every LLM call should save trace artifacts:

- system message
- rendered prompt
- model
- response schema
- raw response
- parsed JSON
- validation result

LLM response schemas should live in `ad_lit_pipeline/llm/schemas.py` or near the
owning step if they are truly step-specific.

Validation must happen after parsing. Never trust the model to follow the schema
semantically just because the response is valid JSON.

Tests for LLM code must use a fake or mocked client. Unit tests must not require
live OpenAI calls.

## Provider Rules

Provider-specific details belong in `ad_lit_pipeline/providers/`.

Examples:

- OpenAlex URL building
- OpenAlex filter translation
- OpenAlex response parsing
- Semantic Scholar request and response logic
- Europe PMC request and response logic
- Crossref request and response logic

Collection steps should call a provider interface. They should not know the
details of each API.

The planner should only receive providers that are actually enabled in the topic
contract or run config. Do not let the LLM choose providers that the fetch step
cannot execute.

## Data And Artifact Rules

Be conservative with data columns.

- Preserve input columns unless there is a clear reason to drop them.
- Prefer appending decision columns over replacing schemas mid-pipeline.
- Keep paper ids stable once created.
- Keep provenance fields when exporting collected candidates.
- Avoid silently overwriting generated files unless the run context says to do
  so.

Important current issue to avoid repeating:

- The existing `screen_scope.py` drops optional metadata such as authors, venue,
  source, URL, and full text path. Future screening code should preserve those
  columns and append scope fields.

For large files:

- process JSONL line by line when practical
- avoid loading large raw API records unless needed
- prefer small representative fixtures in tests
- never inspect huge data files wholesale just to understand their shape

## Run Manifest Rules

When the run manifest exists, every step should record:

- step name
- start and end time
- input artifacts
- output artifacts
- row counts
- model name, if the step uses an LLM
- prompt and response trace paths, if any
- warnings
- error details

Do not make debugging depend only on console output.

## Error Handling Rules

Raise clear errors with artifact paths and step names.

Good:

```text
screen_scope failed: missing required input column 'abstract' in data/raw/foo.csv
```

Less useful:

```text
KeyError: abstract
```

Rules:

- never silently swallow exceptions
- never use bare `except:`
- catch specific exception types when recovery or better context is possible
- use context managers for file and resource cleanup
- use meaningful error messages
- include paper id, candidate id, file path, and step name when relevant

For pipeline control flow:

- invalid input should fail fast
- unsupported provider selection should fail before fetching
- audit issues should be written as data, not hidden in logs
- LLM validation failures should identify the paper or candidate id

When structured logging exists, use `logger.error()` for errors. Until then,
scripts may print concise user-facing summaries, but avoid noisy debug prints.

## Testing Rules

Add or update tests when changing behavior. Start with small fixtures.

Use `pytest` for tests. Follow Arrange-Act-Assert:

1. Arrange input rows, files, fake clients, and context.
2. Act by calling the function or step.
3. Assert outputs, row counts, warnings, and errors.

Good early tests:

- metadata normalization preserves required and optional fields
- scope screening includes, excludes, and marks `needs_decision`
- exclude terms win when configured that way
- scope screening preserves metadata columns
- deduplication chooses DOI before title
- Mantis export picks `categoric` and `semantic` correctly
- provider planner cannot choose unsupported providers
- prompt renderer includes topic-contract criteria

Testing rules:

- write unit tests for new public functions and classes
- mock external dependencies, including APIs, LLMs, databases, and slow file
  systems
- never require live network calls in unit tests
- never commit commented-out tests
- never delete files created as part of testing unless the test writes them
  inside pytest's temporary directory
- keep generated test-output folders in `.gitignore` if they are outside pytest
  temporary directories

## Dependency And Environment Rules

Current repository dependencies are in `requirements.txt`. Local development
uses `.venv`.

Do not migrate this project to `pyproject.toml` yet. Do not introduce package
build metadata, lockfiles, or a new dependency-management workflow as part of the
pipeline refactor.

Rules:

- do not add a new runtime dependency unless the task needs it
- document new runtime dependencies in `requirements.txt`
- use `.venv` for local development when creating or using an environment
- keep Jupyter-only packages such as `ipykernel` and `ipywidgets` out of runtime
  requirements
- do not introduce `pandas`; if a dataframe library is needed, prefer `polars`
- do not introduce dataframe processing for simple CSV streaming tasks
- consider `orjson` for high-volume JSON/JSONL IO only if the performance need
  is real; if added, keep JSON usage behind `ad_lit_pipeline/io/` helpers and
  record the dependency in `requirements.txt`

Notebook-specific guidance:

- use `tqdm` for long-running notebook loops
- use contextual progress-bar descriptions
- explicitly `print()` dataframe objects inside conditional notebook blocks

## Imports

Rules:

- never use wildcard imports
- organize imports as standard library, third-party, local
- avoid importing from `scripts/` inside package modules
- avoid circular imports by keeping shared types in `core/`
- use Ruff import sorting once Ruff is configured

## Type Hints

New code should use type hints for public function signatures.

Rules:

- type all public function parameters and return values
- avoid `Any` unless input shape is genuinely dynamic, such as raw API records
- when `Any` is needed, confine it near IO/provider boundaries and normalize it
  into typed structures quickly
- use `T | None` for nullable values
- prefer dataclasses for simple structured records
- run mypy once it is configured for the project

## Documentation And Docstrings

Public functions, classes, and methods should have docstrings when their purpose
is not obvious from the name and type signature.

Docstrings should document:

- what the function does
- important parameters
- return values
- exceptions raised when relevant

Example:

```python
def calculate_total(items: list[dict[str, float]], tax_rate: float = 0.0) -> float:
    """Calculate the total cost of items including tax.

    Args:
        items: Item dictionaries with `price` keys.
        tax_rate: Tax rate as a decimal, such as `0.08` for 8%.

    Returns:
        Total cost including tax.

    Raises:
        ValueError: If `items` is empty or `tax_rate` is negative.
    """
```

Keep comments up to date. Prefer comments that explain why something exists,
not comments that restate the code.

## Python Style

Use straightforward Python.

Rules:

- follow PEP 8
- use 4 spaces for indentation
- keep line length at 88 characters where practical
- use snake_case for functions and variables
- use PascalCase for classes
- use UPPER_CASE for constants
- use f-strings for string formatting
- use `is` when comparing with `None`, `True`, or `False`
- never use mutable default argument values
- use context managers for files and resources
- use `enumerate()` instead of manual counter variables
- use comprehensions when they improve readability
- avoid global mutable state
- avoid commented-out code
- avoid debug print statements
- do not use emoji or emoji-like Unicode in code, logs, or docs unless a test is
  explicitly about multibyte characters

## Function Design

Rules:

- keep functions focused on one responsibility
- prefer early returns to deep nesting
- keep parameters to five or fewer when practical
- use small dataclasses or config objects when a function needs many related
  values
- separate pure transforms from file IO
- avoid extra helper functions that are only used once and make the code harder
  to read

## Class Design

Rules:

- keep classes focused on one responsibility
- keep `__init__` simple
- use dataclasses for simple data containers
- prefer composition over inheritance
- use `@property` for computed attributes when it improves the public API
- avoid classes when simple functions are clearer

## JSON, CSV, YAML, And Dataframes

CSV:

- use `csv.DictReader` and `csv.DictWriter` for current scripts
- move repeated CSV handling into `ad_lit_pipeline/io/csv_io.py`
- preserve columns unless a step explicitly defines a narrower output contract

JSON/JSONL:

- use shared IO helpers once available
- stream JSONL when possible
- keep raw provider records out of prompts unless explicitly needed
- if `orjson` is adopted, hide it behind IO helpers

YAML:

- use `yaml.safe_load`
- validate shape before using values
- keep topic-contract validation strict and explicit

Dataframes:

- do not use dataframes for simple row-by-row transformations
- if dataframe processing becomes necessary, prefer `polars`
- when inspecting data manually, inspect small subsets rather than huge files

## Security

Rules:

- never store secrets, API keys, or passwords in code
- keep secrets in `.env` or environment variables
- ensure `.env` is ignored by git
- never print or log secrets
- never log URLs containing API keys
- avoid logging sensitive paper metadata unless needed for debugging
- sanitize provider errors if they might include tokens

## Version Control

Rules:

- write clear, descriptive commit messages when asked to commit
- never commit credentials or sensitive data
- never commit debug breakpoints
- never commit commented-out code
- keep generated artifacts out of commits unless the user explicitly asks for
  them

## Formatting And Static Analysis

Target tools:

- Ruff for formatting and linting
- mypy for static type checking
- pytest for testing
- `requirements.txt` plus `.venv` for dependencies and local execution

Before handing off code changes, run the relevant available checks. If a tool is
not configured yet, say so and run the closest practical check.

## Refactoring Rules

Prefer small, reversible moves:

1. Add tests or fixtures around current behavior.
2. Move one script's logic into the package.
3. Turn the script into a wrapper.
4. Run the related tests.
5. Repeat.

Do not combine large behavior changes with file moves. If a step is being moved
and fixed, do it in separate commits or clearly separate the changes.

## Naming Rules

Use names that match pipeline artifacts and docs.

Good step names:

- `normalize_metadata`
- `screen_scope`
- `plan_search`
- `fetch_candidates`
- `deduplicate_candidates`
- `screen_candidates`
- `export_included_candidates`
- `generate_tagging_rules`
- `tag_papers`
- `audit_extraction`
- `export_mantis`

Good artifact names:

- `raw_papers_csv`
- `normalized_papers_csv`
- `scope_screened_csv`
- `topic_contract_yaml`
- `tagging_rules_json`
- `extraction_filled_csv`
- `extraction_audit_csv`
- `mantis_ready_csv`

Avoid vague names like `data`, `output`, `result2`, or `final_file` in shared
code.

## Documentation Rules

When changing pipeline behavior, update at least one of:

- `docs/pipeline_summary.md`
- `docs/refactoring_plan.md`
- this guideline file
- a new focused doc under `docs/`

If a step gains or loses an input/output, update the documentation. If a prompt
policy moves into the topic contract, document where it moved.

## Code Review Checklist

Before finishing a code change, check:

- Does the code live in the right module?
- Did any topic-specific behavior get hard-coded?
- Are prompts rendered from templates or clearly marked as legacy?
- Are LLM calls traceable?
- Are provider details isolated?
- Are input columns preserved unless intentionally changed?
- Are errors actionable?
- Are public functions typed?
- Are tests or fixtures updated?
- Do existing CLI commands still work?
- Does the relevant documentation still match the code?

## Before Committing

When asked to commit, verify:

- tests pass
- type checking passes, if configured
- formatter and linter pass, if configured
- public functions have useful type hints and docstrings
- no commented-out code remains
- no debug statements remain
- no credentials or sensitive data are staged
