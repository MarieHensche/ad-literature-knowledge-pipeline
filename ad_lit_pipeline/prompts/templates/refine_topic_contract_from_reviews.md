You are refining a topic contract for a configurable literature knowledge pipeline.

User research question:
$topic_description

Current topic contract:
$current_contract_json

Review and overview seed papers:
$review_overviews_json

Task:
Return a complete refined topic contract. Use the review and overview seed papers
to replace or improve the knowledge tagging categories so a new user does not
need weeks of manual ontology research before running the pipeline.

Rules:
- Use only the review and overview evidence provided here; do not infer from
  imagined primary papers.
- Prefer evidence from seed reviews with high `review_selection_score`, strong
  topical evidence, useful abstracts, recent years, and citation strength.
- Do not let off-topic seed reviews reshape the ontology, even if they are
  recent or highly cited.
- If a seed review is only broadly related but not close to the research topic,
  use it only for generic context, not for topic-specific tag categories.
- Preserve the research question, topic structure, broad discovery scope,
  rule-based screening, candidate-screening policy, provider settings, and
  search queries. This task is only about knowledge tagging categories and
  values.
- Keep `collection.allowed_providers` to the providers already in the contract.
- In the JSON response, return `topic_structure.secondary_topics` as an array of
  objects with `main_topic_id` and `terms`.
- Treat any existing categories from a template or provisional draft as
  replaceable examples. Keep one only when the review evidence shows that it is
  a crucial knowledge dimension for this topic.
- Add or improve multiple topic-specific knowledge categories for what the
  literature is about: targets, phenomena, populations, outcomes, mechanisms,
  claims, signals, methods, or other domain concepts visible in the review
  evidence.
- Create at least 4 knowledge tagging categories; prefer 5 to 8 when the review
  evidence supports it. A good ontology usually covers several of: studied
  intervention/tool/exposure, population or setting, outcome or target, method
  or study design, measurement or data source, mechanism, claim direction, and
  implementation context.
- Do not add categories for topical fit, paper selection, review status,
  confidence, extraction basis, paper metadata, authors, journals, or single
  paper titles.
- Each category must be a concrete question that can be answered directly from
  a paper, such as what intervention, method, population, setting, outcome,
  mechanism, data source, measurement, or claim type the paper reports.
- Do not create meta-categories whose values are other category types. Avoid
  category IDs such as `knowledge_dimension`, `tag_type`, `evidence_kind`,
  `paper_focus`, `research_area`, or `category`.
- Do not use values such as `method`, `outcome`, `population`, `equity`, or
  `target` as a substitute for separate concrete categories. If those concepts
  matter, create separate categories like `ai_tool_type`,
  `performance_outcome`, `student_group`, `education_setting`,
  `equity_dimension`, or `study_design`.
- Give each tagging category multiple allowed values; do not collapse the
  ontology into one broad category.
- Prefer compact category IDs in lowercase snake_case.
- Prefer compact allowed values in lowercase snake_case.
- Keep each category useful across many papers, not just one seed review.
- Do not create values for author names, journal names, or single paper titles.
- For each category, set `selection` to `single` when at most one value should
  be selected for an applicable paper, or `multi` when several values may be
  selected.
- Set `required` to true only when every applicable paper should receive at
  least one value. Most generated knowledge categories should be optional, and
  optional categories may receive zero values.
- Use `applies_when` to define conditional sub-categories. Use null when the
  category applies generally; otherwise set `category_id` and triggering
  `values` from another category.
- If a category only applies after another category has a specific value, that
  relationship must be represented in `applies_when`.
- Conditional sub-categories must depend on concrete parent values, not broad
  values like `method`, `outcome`, `population`, or `target`.
- Include `mixed_or_unclear`, `unclear`, or `not_reported` values where ambiguity
  or missing information is likely.
- Keep category value lists small enough for consistent tagging, usually 4 to 12
  values.
- Return JSON matching the schema. For `tagging.categories`, return an array of
  category objects with `category_id`, `description`, `required`, `selection`,
  `values`, and `applies_when`.
