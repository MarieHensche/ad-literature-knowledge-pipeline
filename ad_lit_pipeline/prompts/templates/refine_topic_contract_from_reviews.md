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
- Prefer evidence from seed reviews with high `review_selection_score`, strong
  topical evidence, useful abstracts, recent years, and citation strength.
- Do not let off-topic seed reviews reshape the ontology, even if they are
  recent or highly cited.
- If a seed review is only broadly related but not close to the research topic,
  use it only for generic context, not for topic-specific tag categories.
- Preserve the semantic roles in the user's topic. If the topic names a
  phenomenon/intervention/tool, a context or population, and an outcome, keep
  those dimensions distinct in scope rules, search queries, and tagging
  categories.
- Identify the primary subject anchor. In topics phrased like "use of X in Y and
  its impact on Z", X-in-Y is the primary anchor and Z is an outcome dimension.
  Do not let the outcome phrase become the main topic.
- Do not redefine a central topic term as merely a research method, prediction
  model, measurement tool, or evaluation technique unless the user explicitly
  asks for method papers.
- Do not broaden named settings, institutional levels, populations, or domains.
  For example, if the user says school education, college, university, higher
  education, or general education should be adjacent rather than core unless the
  user explicitly includes them.
- Keep `core_topic` stricter than broad discovery: core should require the
  central phenomenon, requested context or population, and requested
  outcome/relationship when those are present. Method-only or context-shifted
  papers should be adjacent or out of scope, not core.
- Preserve the research question, broad discovery scope, provider settings, and
  search queries unless the review evidence shows a clear improvement.
- Keep `collection.allowed_providers` to the providers already in the contract.
- Include `research_target`, `main_topic_category`, and `review_status` in
  `tagging.categories`.
- For `main_topic_category`, use exactly these values: `core_topic`,
  `adjacent_but_relevant`, `out_of_scope`, `mixed_or_unclear`, and `unclear`.
  This category controls Mantis export eligibility.
- For `review_status`, use values `ai_tagged`, `human_reviewed`,
  `full_text_needed`, and `excluded_from_scope`, and mark it required.
- Set `tagging.fallback_policy.review_status` to `ai_tagged`.
- Add or improve multiple topic-specific knowledge categories for what the
  literature is about: targets, phenomena, populations, outcomes, mechanisms,
  claims, signals, or other domain concepts visible in the review evidence.
- Give each tagging category multiple allowed values; do not collapse the
  ontology into one broad category.
- Prefer compact category IDs in lowercase snake_case.
- Prefer compact allowed values in lowercase snake_case.
- Keep each category useful across many papers, not just one seed review.
- Do not create values for author names, journal names, or single paper titles.
- Include `mixed_or_unclear`, `unclear`, or `not_reported` values where ambiguity
  or missing information is likely.
- Keep category value lists small enough for consistent tagging, usually 4 to 12
  values.
- Keep `rule_based_screening.include_terms` broad, atomic, and recall-oriented
  enough to catch synonyms, adjacent phrasing, plural/singular variants, and
  common abbreviations or acronyms such as AI/ML/GPA when relevant.
- Add important topic-specific tag values and category concepts to
  `rule_based_screening.include_terms` when they are useful screening signals.
- Return JSON matching the schema. For `tagging.categories`, return an array of
  category objects with `category_id`, `required`, and `values`.
