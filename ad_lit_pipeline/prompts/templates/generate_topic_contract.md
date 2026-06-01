You are drafting a topic contract for a configurable literature knowledge pipeline.

User research question:
$topic_description

Base contract template:
$base_contract_json

Task:
Fill out a complete topic contract draft for the research question.

Rules:
- Keep the contract useful for broad discovery, not only strict final inclusion.
- Use general, reusable language; do not hard-code assumptions from unrelated example topics.
- Set `topic_id` to a lowercase snake_case identifier.
- Keep `collection.allowed_providers` to the providers available in the template.
- Preserve the semantic roles in the user's topic. If the topic names a
  phenomenon/intervention/tool, a context or population, and an outcome, keep
  those dimensions distinct in scope rules, search queries, and tagging
  categories.
- Identify the primary subject anchor. In topics phrased like "use of X in Y and
  its impact on Z", X-in-Y is the primary anchor and Z is an outcome dimension.
  Do not let the outcome phrase become the main topic.
- Do not redefine a central topic term as merely a research method, prediction
  model, measurement tool, or evaluation technique unless the user explicitly
  asks for method papers. For example, a topic about use of a tool in a setting
  is different from papers that use that tool to predict an outcome.
- Do not broaden named settings, institutional levels, populations, or domains.
  For example, if the user says school education, college, university, higher
  education, or general education should be adjacent rather than core unless the
  user explicitly includes them.
- Make core inclusion criteria stricter than broad discovery criteria:
  `core_topic` should require the central phenomenon, requested context or
  population, and requested outcome/relationship when those are present.
- Include `research_target`, `main_topic_category`, and `review_status` in `tagging.categories`.
- For `main_topic_category`, use exactly these values: `core_topic`, `adjacent_but_relevant`, `out_of_scope`, `mixed_or_unclear`, and `unclear`. This category controls Mantis export eligibility.
- For `review_status`, use values `ai_tagged`, `human_reviewed`, `full_text_needed`, and `excluded_from_scope`, and mark it required.
- Set `tagging.fallback_policy.review_status` to `ai_tagged`.
- Add multiple topic-specific knowledge tagging categories that would help later extraction.
- Give each tagging category multiple allowed values; do not collapse the ontology into one broad category.
- Include `mixed_or_unclear` and `unclear` values where ambiguity is expected.
- Make `scope.include_criteria` cover direct papers and meaningfully adjacent
  papers, while clearly distinguishing strict core papers from adjacent papers.
- Keep `scope.exclude_criteria` for clear mismatches only.
- Make `scope.boundary_rules` describe when related or tangential papers should
  stay in for human review, and when method-only or context-shifted papers should
  be adjacent rather than core.
- Make `rule_based_screening.include_terms` broad, atomic, and recall-oriented enough to catch synonyms, adjacent phrasing, plural/singular variants, and common abbreviations or acronyms such as AI/ML/GPA when relevant.
- Add important topic-specific tag values and category concepts to `rule_based_screening.include_terms` when they are useful search or screening signals.
- Keep `rule_based_screening.exclude_terms` short and only for hard negatives.
- Set candidate screening so borderline or tangentially relevant candidates are included for later review unless clearly outside the topic.
- Include reviews unless the research question explicitly asks for primary studies only.
- Add 4 to 8 `collection.search_queries`; each query should search a different phrasing, synonym set, population, method, application, or adjacent angle.
- Ensure several search queries preserve all core dimensions from the user topic,
  especially the requested context or population. Adjacent queries are allowed
  but should not dominate the plan.
- Search queries should be precise enough for OpenAlex but not so narrow that useful candidate papers disappear.
- Return JSON matching the schema. For `tagging.categories`, return an array of category objects with `category_id`, `required`, and `values`.
