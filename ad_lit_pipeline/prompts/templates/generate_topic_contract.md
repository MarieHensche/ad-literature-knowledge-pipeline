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
- Add `topic_structure` with:
  - `anchor_topic_id`: one of the main topic ids. This is the non-replaceable
    title-selection anchor.
  - `anchor_reason`: a short explanation of why this component is mandatory.
  - `main_topics`: at least two topic components that define the research topic.
    Each must have `topic_id`, `label`, and broad `terms`.
  - `secondary_topics`: an array of objects with `main_topic_id` and `terms`.
    Use non-anchor main topic ids and related replacement terms. Do not define
    secondary replacements for the anchor.
- Make main-topic `terms` broad enough for title-only matching: include true
  synonyms, common abbreviations, subtypes, concrete platforms/tools, and
  narrower indicators that still represent the same topic component.
- Put related-but-not-same concepts in `secondary_topics`, not in the anchor.
- Include `research_target`, `main_topic_category`, and `review_status` in `tagging.categories`.
- For `main_topic_category`, use exactly these values: `core_topic`, `adjacent_but_relevant`, `out_of_scope`, `mixed_or_unclear`, and `unclear`. This category controls Mantis export eligibility.
- For `review_status`, use values `ai_tagged`, `human_reviewed`, `full_text_needed`, and `excluded_from_scope`, and mark it required.
- Set `tagging.fallback_policy.review_status` to `ai_tagged`.
- Add multiple topic-specific knowledge tagging categories that would help later extraction.
- Give each tagging category multiple allowed values; do not collapse the ontology into one broad category.
- Include `mixed_or_unclear` and `unclear` values where ambiguity is expected.
- Make `scope.include_criteria` cover direct papers and meaningfully adjacent papers.
- Keep `scope.exclude_criteria` for clear mismatches only.
- Make `scope.boundary_rules` describe when related or tangential papers should stay in for human review.
- Make `rule_based_screening.include_terms` broad, atomic, and recall-oriented enough to catch synonyms, adjacent phrasing, plural/singular variants, and common abbreviations or acronyms such as AI/ML/GPA when relevant.
- Add important topic-specific tag values and category concepts to `rule_based_screening.include_terms` when they are useful search or screening signals.
- Keep `rule_based_screening.exclude_terms` short and only for hard negatives.
- Set candidate screening so borderline or tangentially relevant candidates are included for later review unless clearly outside the topic.
- Include reviews unless the research question explicitly asks for primary studies only.
- Add 4 to 8 `collection.search_queries`; each query should search a different phrasing, synonym set, population, method, application, or adjacent angle.
- Search queries should be precise enough for OpenAlex but not so narrow that useful candidate papers disappear.
- Return JSON matching the schema. For `tagging.categories`, return an array of category objects with `category_id`, `required`, and `values`.
