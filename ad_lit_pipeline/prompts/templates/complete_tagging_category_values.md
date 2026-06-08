You complete values for user-requested literature tagging categories.

Research topic:

$research_topic_json

Topic structure:

$topic_structure_json

Existing categories and values:

$existing_categories_json

User-requested categories needing values:

$requested_categories_json

Evidence:

$evidence_json

Return JSON only.

Rules:

- Return values only for the requested category ids.
- Do not add, remove, or rename categories.
- Use the evidence and topic structure to propose concrete values that could be
  assigned to individual papers.
- Values must be compact lowercase snake_case strings.
- Prefer 3 to 8 values per category.
- Avoid broad catch-all values such as unclear, not_reported, mixed_or_unclear,
  and other.
- Avoid generic category-type values such as method, outcome, population, or
  study_design unless the user-requested category specifically requires a
  concrete topic-specific variant.
