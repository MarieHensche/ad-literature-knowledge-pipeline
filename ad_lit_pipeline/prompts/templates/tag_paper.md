You are tagging one scientific paper for a knowledge-map pipeline.

Research topic:
$research_topic_json

Topic scope:
$scope_text

Paper:
$paper_json

Allowed categories and values:
$categories_json

Fixed tagging rules:
$rules_json

Task:
Assign the best-fitting knowledge tags for this paper.

Rules:
- Use only the allowed category IDs.
- Use only allowed values listed for each category.
- Return every category as an array of selected values.
- For required single-selection categories, return exactly one value in the array.
- For optional single-selection categories, return zero or one value depending
  on applicability and evidence.
- For multi-selection categories, return zero, one, or more values depending on
  applicability and evidence.
- If a rule includes `applies_when`, return an empty array unless the referenced
  parent category contains one of the triggering values.
- Use a category fallback value only when the fixed rule has a non-null
  fallback_value.
- For required categories with no fallback_value, choose the best concrete value
  from the allowed exhaustive partition using the title, abstract, and full-text
  evidence.
- Do not select the broadest or first-listed value unless the evidence supports
  it better than the other allowed values.
- For optional categories with no supported value, return an empty array.
- Do not combine fallback values such as `not_reported`, `unclear`, or
  `mixed_or_unclear` with concrete values in the same category.
- Do not invent new values.
- If `main_topic_category` offers `core_topic`, `adjacent_but_relevant`, and
  `out_of_scope`, use it as a strict topical-fit judgment: choose `core_topic`
  only for papers directly about the research topic, `adjacent_but_relevant`
  for papers that meaningfully support the topic but are not central, and
  `out_of_scope` for weak or mismatched papers.
- If a category requires a single main-topic value, choose the one best-supported
  value rather than a broad umbrella value.
- main_knowledge_claim should be one concise sentence describing what the paper contributes to the research topic.
$review_status_instruction
