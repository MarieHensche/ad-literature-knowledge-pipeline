# Topic Contract Bootstrap And Refinement Implementation Plan

This plan is for an implementation agent working in this repository. It
describes how to separate the first topic-contract draft from the final
review-refined tagging ontology, and how to add targeted repair only where it
belongs.

## Problem Summary

The collection workflow is intended to run in this order:

1. `generate_topic_contract`
2. `fetch_review_overviews`
3. `refine_topic_contract`
4. normal collection steps

The first topic contract should be a bootstrap contract for review discovery. It
only needs enough structure to find relevant reviews and overviews:

- `research_topic`
- `topic_structure`
- `scope`
- `rule_based_screening`
- `candidate_screening`
- `collection.search_queries`
- structurally valid placeholder tagging categories because the contract schema
  currently requires tagging

The final, strict knowledge tagging ontology should be produced during
`refine_topic_contract`, after review/overview seed papers have been fetched.

Current issue: `generate_topic_contract.call_llm()` runs
`validate_generated_tagging_quality()` before review fetching can happen. This
causes the bootstrap contract to fail on final ontology rules even though the
ontology is supposed to be refined later from reviews.

## Desired Behavior

The new flow should be:

```text
generate bootstrap topic contract
-> validate structure only
-> fetch review/overview seed papers
-> refine tagging ontology using review evidence
-> strict semantic tagging validation
-> targeted repair for refined tagging failures
-> full refinement retry only when targeted repair fails
```

If no review/overview seed papers are found, still call the refinement prompt.
The prompt should receive an empty seed list plus an explicit warning that no
reviews were found. The refiner should then build a final ontology from the
research question and current discovery contract while clearly treating that as
a fallback path.

## Non-Goals

- Do not change provider behavior beyond what is needed for this workflow.
- Do not remove `validate_generated_tagging_quality()` from the project.
- Do not migrate dependency management or introduce new runtime dependencies.
- Do not redesign the entire topic-contract schema unless required by focused
  tests.
- Do not introduce broad refactors outside `ad_lit_pipeline/`.

## Files To Inspect First

- `ad_lit_pipeline/steps/collection/generate_topic_contract.py`
- `ad_lit_pipeline/steps/collection/refine_topic_contract.py`
- `ad_lit_pipeline/topics/contract.py`
- `ad_lit_pipeline/llm/schemas.py`
- `ad_lit_pipeline/prompts/templates/generate_topic_contract.md`
- `ad_lit_pipeline/prompts/templates/refine_topic_contract_from_reviews.md`
- `ad_lit_pipeline/prompts/render.py`
- `tests/test_llm_steps.py`
- `tests/test_prompts.py`
- `tests/test_cli_runner.py`
- `tests/test_non_llm_steps.py`

## Step 1: Split Bootstrap Validation From Final Ontology Validation

Update `generate_topic_contract.call_llm()` so the initial generated contract
only runs structural validation:

```python
contract = contract_from_model_payload(result.parsed)
validate_topic_contract(contract)
return contract, trace_paths
```

Do not call `validate_generated_tagging_quality()` in
`generate_topic_contract`.

Keep deterministic normalization through `contract_from_model_payload()`. It is
still useful because downstream code expects stable category ids and values.

Expected result:

- Bootstrap generation can proceed even with provisional or imperfect tagging.
- `fetch_review_overviews` can run because it only needs the discovery portions
  of the contract.

Tests to update:

- Existing `generate_topic_contract` retry tests that assume weak tagging causes
  full-contract retries should be changed or removed.
- Add/adjust a test proving weak generated tagging no longer blocks the
  bootstrap contract.
- Keep tests proving structural failures still retry or fail.

## Step 2: Relax The Bootstrap Prompt

Rewrite `generate_topic_contract.md` to be discovery-focused.

Keep rules for:

- lowercase snake_case `topic_id`
- `topic_structure`
- broad title-only terms
- include/exclude/boundary scope
- recall-oriented `rule_based_screening.include_terms`
- candidate screening policies
- 4 to 8 review-friendly `collection.search_queries`
- allowed providers from the template
- structurally valid tagging categories

Remove or drastically shorten rules for:

- six to ten final knowledge categories
- review-derived ontology quality
- generic/boilerplate category rejection
- conditional ontology hierarchy
- value distribution checks

The bootstrap prompt should tell the model that tagging categories are
provisional and will be replaced during review-based refinement.

Suggested wording:

```text
Tagging categories in this first contract are provisional. Create only a simple
structurally valid tagging section so the contract can pass shape validation.
Do not spend effort building the final extraction ontology; that will be refined
from review and overview papers in a later step.
```

Potential schema issue:

`topic_contract_schema()` currently uses `minItems: 6` for
`tagging.categories`. If the bootstrap prompt asks for fewer provisional
categories, update `topic_contract_schema()` to accept a parameter such as:

```python
def topic_contract_schema(
    provider_names: list[str],
    min_tagging_categories: int = 6,
) -> dict[str, Any]:
```

Then call it with:

- `min_tagging_categories=1` from `generate_topic_contract`
- default `6` from `refine_topic_contract`

Keep `validate_topic_contract()` requiring only non-empty categories. The strict
six-category rule should remain inside `validate_generated_tagging_quality()`.

## Step 3: Prevent Bootstrap Categories From Anchoring Refinement

The refinement prompt currently includes the full current contract, including
provisional categories. The prompt says existing categories are replaceable, but
the model can still anchor on them.

Add a helper in `refine_topic_contract.py` or `prompts/render.py` that builds a
refinement prompt contract with provisional tagging categories omitted.

Suggested helper:

```python
def refinement_context_contract(current_contract: dict[str, Any]) -> dict[str, Any]:
    context = deepcopy(current_contract)
    tagging = context.get("tagging")
    if isinstance(tagging, dict):
        context["tagging"] = {
            "fallback_policy": deepcopy(tagging.get("fallback_policy", {})),
            "categories": [],
            "categories_note": (
                "Bootstrap categories omitted. Build final categories from "
                "review evidence and the research question."
            ),
        }
    return context
```

Because the full topic-contract schema may reject `categories_note` if this
object is sent back by the model, make sure this helper is only used for prompt
context, not as the object to validate or merge.

Update `render_refine_topic_contract_prompt()` call sites so the prompt receives
this context contract instead of the raw current contract.

Alternative if avoiding an extra field:

```json
"tagging": {
  "fallback_policy": {...},
  "categories": []
}
```

Then explain in text that categories are intentionally omitted.

## Step 4: Always Call Refinement, Even Without Reviews

Current `refine_topic_contract.run()` skips LLM refinement when
`review_overviews` is empty and leaves the bootstrap contract unchanged.

Change this behavior:

- Always call `call_llm()`.
- Pass the empty review list.
- Add a warning to the `StepResult` when no reviews were found.
- Ensure the prompt explicitly tells the model no reviews were found.

Suggested warning:

```text
No review/overview seed papers were available; refined tagging ontology from
the research question and bootstrap discovery contract only.
```

Update `refine_topic_contract_from_reviews.md` so it handles empty review lists:

```text
If the review and overview seed paper list is empty, build the best final
tagging ontology you can from the research question and discovery contract.
Do not preserve provisional bootstrap categories as evidence. The pipeline will
emit a warning that this ontology was not review-seeded.
```

Keep strict validation after this fallback refinement. Even without reviews, the
output is now intended to be the final tagging ontology.

## Step 5: Add Structured Tagging Quality Issues

Add a dataclass near `generated_tagging_quality_issues()` in `contract.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class TaggingQualityIssue:
    code: str
    category_id: str | None
    values: tuple[str, ...] = ()
    message: str = ""
```

Add a new function:

```python
def generated_tagging_quality_issue_records(
    contract: dict[str, Any],
) -> list[TaggingQualityIssue]:
    ...
```

Keep the existing public string function:

```python
def generated_tagging_quality_issues(contract: dict[str, Any]) -> list[str]:
    return [issue.message for issue in generated_tagging_quality_issue_records(contract)]
```

This preserves current behavior while enabling programmatic targeted repair.

Suggested issue codes:

- `too_few_categories`
- `meta_category_id`
- `non_snake_category_id`
- `boilerplate_category_id`
- `too_few_values`
- `catchall_values`
- `meta_values`
- `non_snake_values`
- `meta_dependency`
- `broad_dependency_values`
- `retired_category_id`

Tests:

- Existing string issue tests should still pass.
- Add tests for issue record codes and category ids.

## Step 6: Add Targeted Repair For Refined Contracts Only

Targeted repair should run inside `refine_topic_contract.call_llm()` after a
refined candidate fails `validate_generated_tagging_quality()`.

Do not add targeted repair to `generate_topic_contract`; bootstrap generation
should not need strict semantic repair.

Repairable issue types:

- `boilerplate_category_id`
- `meta_category_id`
- `meta_values`
- `catchall_values`
- `too_few_values`
- `too_few_categories`
- `retired_category_id`
- `meta_dependency`
- `broad_dependency_values`

Usually deterministic or already normalized:

- `non_snake_category_id`
- `non_snake_values`

Full refinement retry should remain the fallback when:

- the contract is structurally invalid
- more than half the categories require replacement
- targeted repair fails validation

## Step 7: Add A Repair Patch Schema

Add a schema helper in `llm/schemas.py`, for example:

```python
def topic_contract_tagging_repair_schema() -> dict[str, Any]:
    ...
```

Expected response:

```json
{
  "remove_category_ids": ["study_design"],
  "upsert_categories": [
    {
      "category_id": "green_space_exposure_pattern",
      "description": "Green-space exposure distinctions visible in the reviewed literature.",
      "required": false,
      "selection": "multi",
      "values": ["park_access", "tree_canopy", "greenway_use"],
      "applies_when": null
    }
  ],
  "repair_notes": [
    "Replaced generic study_design with a topic-specific exposure category."
  ]
}
```

The repair response should only patch `tagging.categories`. It should not return
a full contract.

## Step 8: Add A Targeted Repair Prompt

Add a new template:

```text
ad_lit_pipeline/prompts/templates/repair_topic_contract_tagging.md
```

Add a renderer in `prompts/render.py`.

The prompt should include:

- user research question
- review/overview seed papers, including empty list when no reviews were found
- the failed refined contract candidate
- structured validation issues
- existing category ids
- forbidden generic ids and catchall values
- patch-only response instructions

Prompt guidance:

```text
You are repairing only the tagging ontology of an already refined topic contract.

Return only a JSON patch with remove_category_ids, upsert_categories, and
repair_notes.

Do not modify research_topic, topic_structure, scope, rule_based_screening,
candidate_screening, or collection.

Keep valid existing categories unless they are directly affected by a listed
validation issue.

If repairing a retired category, remove it and replace it with direct
topic-specific categories only when needed.

If a category depends on a repaired parent value, repair the dependency or
replace the dependent category.

If no review seed papers are available, use the research question and discovery
contract as fallback context, but do not preserve provisional bootstrap
categories unless they are genuinely useful as final knowledge dimensions.
```

## Step 9: Apply Repair Patches Safely

Add a helper in `refine_topic_contract.py`:

```python
def apply_tagging_repair_patch(
    contract: dict[str, Any],
    patch: dict[str, Any],
) -> dict[str, Any]:
    ...
```

Behavior:

- Deep-copy the failed refined contract.
- Normalize all patch category ids and values with `normalize_tagging_label()`.
- Normalize `applies_when.category_id` and `applies_when.values`.
- Remove listed categories, including retired categories.
- Upsert replacement categories.
- Preserve category order where practical.
- Validate with `validate_topic_contract()`.
- Validate with `validate_generated_tagging_quality()`.

If the patch introduces duplicate ids after normalization, raise a clear error.

If the patch references unknown parent categories in `applies_when`, let
`validate_topic_contract()` raise the existing clear dependency error.

## Step 10: Update Refinement Retry Flow

Current refinement flow retries the full refined contract on validation failure.
Modify it to:

1. Generate a full refined contract candidate.
2. Validate structure.
3. Merge refined tagging into current contract.
4. Run strict semantic validation.
5. If semantic validation fails, collect structured issue records.
6. Try targeted repair once for this candidate when issue records are repairable.
7. If repaired contract validates, return it.
8. If repair fails, continue to existing full refinement retry.

Keep the existing max attempt count for full refinement attempts.

Add trace names for repair calls, for example:

- `contract_refinement_repair`
- `contract_refinement_retry_2_repair`
- `contract_refinement_retry_3_repair`

Make sure repair trace paths are included in the returned `StepResult`.

## Step 11: Tests To Add Or Update

Update `tests/test_llm_steps.py`:

- `generate_topic_contract` accepts weak provisional tagging and writes a
  structurally valid bootstrap contract.
- `generate_topic_contract` still fails or retries on structural contract errors.
- `refine_topic_contract` is called even when review overviews JSONL is empty.
- Empty-review refinement returns a warning in `StepResult.warnings`.
- Refinement prompt omits or neutralizes bootstrap categories.
- Refined contract semantic failures trigger targeted repair before full retry.
- Targeted repair replaces `study_design` without changing scope, collection, or
  topic structure.
- Targeted repair removes retired categories when they appear.
- Failed targeted repair falls back to full refinement retry.
- Repair trace paths are returned.

Update `tests/test_prompts.py`:

- Bootstrap generation prompt says tagging is provisional.
- Bootstrap generation prompt no longer contains the long final ontology rule
  block.
- Refinement prompt says bootstrap categories are omitted/provisional.
- Refinement prompt contains guidance for empty review lists.
- Repair prompt includes patch-only instructions.

Update `tests/test_topic_contract.py`:

- Structured issue records contain expected codes and category ids.
- Existing human-readable issue messages remain compatible.

Update `tests/test_cli_runner.py` only if dry-run output or step behavior
changes.

## Step 12: Suggested Commit Checkpoints

Build this in small commits after each running draft.

Recommended sequence:

1. Commit prompt and validation-placement change:
   - generation skips semantic quality validation
   - generation prompt is discovery-focused
   - focused tests pass

2. Commit refinement context and empty-review behavior:
   - bootstrap categories omitted from refinement prompt context
   - refinement always runs
   - empty-review warning added
   - focused tests pass

3. Commit structured issue dataclass:
   - issue record function added
   - existing string issue API preserved
   - tests pass

4. Commit targeted repair schema, prompt, and patch application:
   - repair prompt/template added
   - patch schema added
   - patch merge helper added
   - unit tests pass

5. Commit refinement retry integration:
   - targeted repair call wired into refinement loop
   - trace paths included
   - fallback to full retry preserved
   - focused LLM step tests pass

6. Final cleanup commit:
   - docs updated if needed
   - broader tests pass
   - no unrelated generated artifacts committed

Do not commit generated `runs/`, `data/raw/`, or `data/processed/` outputs unless
the user explicitly asks for them.

## Verification Commands

Run focused tests after each checkpoint:

```bash
pytest tests/test_llm_steps.py
pytest tests/test_prompts.py
pytest tests/test_topic_contract.py
pytest tests/test_cli_runner.py
```

Run broader tests before the final commit:

```bash
pytest
```

If the local environment does not have `pytest` on `PATH`, use the repository's
active virtual environment or report the exact command that failed.

## Code Quality Instructions For The Implementing Agent

- Keep `scripts/` as thin wrappers.
- Put reusable behavior in `ad_lit_pipeline/`.
- Preserve existing CLI behavior except for the intentional validation placement
  and empty-review refinement behavior.
- Keep side effects near step edges.
- Use `csv.DictReader` and `csv.DictWriter` patterns where relevant.
- Do not add runtime dependencies.
- Use clear `ValueError` messages with step names, category ids, and traceable
  issue context.
- Do not swallow exceptions silently.
- Add focused tests for every behavior change.
- Keep code straightforward and typed for public helpers.
- Avoid broad refactors and unrelated formatting churn.
