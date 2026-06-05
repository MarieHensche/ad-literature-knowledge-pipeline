You are drafting a bootstrap topic contract for a configurable literature
knowledge pipeline.

User research question:
$topic_description

Base contract template:
$base_contract_json

Task:
Fill out a complete discovery-focused topic contract draft for the research
question. This first contract is used to find relevant review and overview
papers. The final knowledge-tagging ontology will be rebuilt in a later
review-based refinement step.

Rules:
- Keep the contract useful for broad discovery, not only strict final inclusion.
- Use general, reusable language; do not hard-code assumptions from unrelated
  example topics.
- Set `topic_id` to a lowercase snake_case identifier.
- Keep `collection.allowed_providers` to the providers available in the
  template.
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
- Make `scope.include_criteria` cover direct papers and meaningfully adjacent
  papers, including reviews unless the research question explicitly asks for
  primary studies only.
- Keep `scope.exclude_criteria` for clear mismatches only.
- Make `scope.boundary_rules` describe when related or tangential papers should
  stay in for human review.
- Make `rule_based_screening.include_terms` broad, atomic, and recall-oriented
  enough to catch synonyms, adjacent phrasing, plural/singular variants, and
  common abbreviations or acronyms such as AI/ML/GPA when relevant.
- Do not make `rule_based_screening.include_terms` depend on the provisional
  tagging categories. Screening terms should come from the research topic,
  topic structure, and scope.
- Keep `rule_based_screening.exclude_terms` short and only for hard negatives.
- Set candidate screening so borderline or tangentially relevant candidates are
  included for later review unless clearly outside the topic.
- Add 4 to 8 `collection.search_queries`; each query should search a different
  phrasing, synonym set, population, method, application, or adjacent angle.
- Search queries should be precise enough for OpenAlex but not so narrow that
  useful candidate papers disappear.
- Treat any categories in the base contract template as examples only.
- Tagging categories in this first contract are provisional. Create only a
  simple structurally valid tagging section so the contract can pass shape
  validation. Do not spend effort building the final extraction ontology; that
  will be refined from review and overview papers in a later step.
- Include at least one provisional tagging category. Prefer `knowledge_goal` as
  a simple root placeholder with `required` true, `selection` single,
  `applies_when` null, and a few lowercase snake_case values.
- Category IDs and allowed values must use lowercase snake_case. Do not return
  labels with spaces, slashes, punctuation, or title case.
- For each category, set `selection` to `single` when at most one value should
  be selected for an applicable paper, or `multi` when several values may be
  selected.
- Use `applies_when` to define conditional sub-categories only when needed. Use
  null when the category applies generally.
- Return JSON matching the schema. For `tagging.categories`, return an array of
  category objects with `category_id`, `description`, `required`, `selection`,
  `values`, and `applies_when`.
