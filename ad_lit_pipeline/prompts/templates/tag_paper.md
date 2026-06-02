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
- If a category applies but the paper does not provide enough information, use
  the category fallback value from the fixed rules.
- Do not invent new values.
- If `main_topic_category` offers `core_topic`, `adjacent_but_relevant`, and
  `out_of_scope`, use it as a strict topical-fit judgment: choose `core_topic`
  only for papers directly about the research topic, `adjacent_but_relevant`
  for papers that meaningfully support the topic but are not central, and
  `out_of_scope` for weak or mismatched papers.
- main_knowledge_claim should be one concise sentence describing what the paper contributes to the research topic.
$review_status_instruction
