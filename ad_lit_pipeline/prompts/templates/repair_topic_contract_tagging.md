You are repairing only the tagging ontology of an already refined topic
contract.

User research question:
$topic_description

Extracted review full-text evidence:
$review_overviews_json

Failed refined contract candidate:
$failed_contract_json

Structured validation issues:
$validation_issues_json

Existing category ids:
$existing_category_ids_json

Forbidden generic category ids:
$forbidden_generic_ids_json

Forbidden catch-all values:
$forbidden_catchall_values_json

Task:
Return only a JSON patch with `remove_category_ids`, `upsert_categories`, and
`repair_notes`.

Rules:
- Do not modify `research_topic`, `topic_structure`, `scope`,
  `rule_based_screening`, `candidate_screening`, or `collection`.
- Patch only `tagging.categories`.
- Keep valid existing categories unless they are directly affected by a listed
  validation issue.
- Remove or replace generic boilerplate categories with topic-specific
  review-derived categories.
- Use only `full_text_evidence` from extracted review records when choosing
  replacement categories and values. Do not use abstracts, titles, query
  metadata, citation metadata, or imagined primary papers to repair the ontology.
- Do not introduce catch-all values such as `unclear`, `not_reported`, `other`,
  `mixed_or_unclear`, `not_applicable`, or `unknown`.
- If repairing `knowledge_goal`, return the complete replacement
  `knowledge_goal` category with at least three concrete primary
  research-focus facet values, `required` true, `selection` single, and
  `applies_when` null.
- Every `knowledge_goal` value must be the exact `category_id` of a sibling
  facet category that also appears in `upsert_categories` or already exists in
  the failed contract. If a matching facet category is missing or affected by
  the issue, include it in `upsert_categories` with detailed allowed values
  grounded only in review full-text evidence.
- Do not repair `knowledge_goal` with whole-question or action values such as
  `effect_of_x`, `impact_of_x`, `role_of_x`, `improving_x`, or `supporting_x`.
- If a category depends on a repaired parent value, repair the dependency or
  replace the dependent category.
- If no extracted review full-text evidence is available, the pipeline should
  fail before this prompt is called. Do not invent a fallback ontology from the
  research question or discovery contract alone.
- Use compact lowercase snake_case category ids and values.
- For each `upsert_categories` item, include `category_id`, `description`,
  `required`, `selection`, `values`, and `applies_when`.
- Return JSON matching the patch schema. Do not return a full topic contract.
