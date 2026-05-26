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
- Include `research_target`, `main_topic_category`, and `review_status` in `tagging.categories`.
- For `review_status`, use values `ai_tagged`, `human_reviewed`, `needs_decision`, `full_text_needed`, and `excluded_from_scope`, and mark it required.
- Add a small set of topic-specific tagging categories that would help later extraction.
- Include `mixed_or_unclear` and `unclear` values where ambiguity is expected.
- Make `scope.include_criteria` cover direct papers and meaningfully adjacent papers.
- Keep `scope.exclude_criteria` for clear mismatches only.
- Make `scope.boundary_rules` describe when related or tangential papers should stay in for human review.
- Make `rule_based_screening.include_terms` broad enough to catch synonyms and adjacent phrasing.
- Keep `rule_based_screening.exclude_terms` short and only for hard negatives.
- Set candidate screening so borderline or tangentially relevant candidates are included for later review unless clearly outside the topic.
- Include reviews unless the research question explicitly asks for primary studies only.
- Add 4 to 8 `collection.search_queries`; each query should search a different phrasing, synonym set, population, method, application, or adjacent angle.
- Search queries should be precise enough for OpenAlex but not so narrow that useful candidate papers disappear.
- Return JSON matching the schema. For `tagging.categories`, return an array of category objects with `category_id`, `required`, and `values`.
