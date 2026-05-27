You are refining a topic contract for a configurable literature knowledge pipeline.

User research question:
$topic_description

Current topic contract:
$current_contract_json

Review and overview seed papers:
$review_overviews_json

Task:
Return a complete refined topic contract. Use the review and overview seed papers
to improve the tagging categories so a new user does not need weeks of manual
ontology research before running the pipeline.

Rules:
- Use only the review and overview evidence provided here; do not infer from
  imagined primary papers.
- Preserve the research question, broad discovery scope, provider settings, and
  search queries unless the review evidence shows a clear improvement.
- Keep `collection.allowed_providers` to the providers already in the contract.
- Include `research_target`, `main_topic_category`, and `review_status` in
  `tagging.categories`.
- For `review_status`, use values `ai_tagged`, `human_reviewed`,
  `needs_decision`, `full_text_needed`, and `excluded_from_scope`, and mark it
  required.
- Add or improve topic-specific knowledge categories for what the literature is
  about: targets, phenomena, populations, outcomes, mechanisms, claims, or other
  domain concepts visible in the review evidence.
- Add or improve topic-specific know-how categories for how the literature works:
  methods, measurements, evidence sources, datasets, modalities, validation
  designs, study families, or evaluation practices visible in the review
  evidence.
- Prefer compact category IDs in lowercase snake_case.
- Prefer compact allowed values in lowercase snake_case.
- Keep each category useful across many papers, not just one seed review.
- Do not create values for author names, journal names, or single paper titles.
- Include `mixed_or_unclear`, `unclear`, or `not_reported` values where ambiguity
  or missing information is likely.
- Keep category value lists small enough for consistent tagging, usually 4 to 12
  values.
- Return JSON matching the schema. For `tagging.categories`, return an array of
  category objects with `category_id`, `required`, and `values`.
