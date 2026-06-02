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
- Treat any categories in the base contract template as examples only. Replace
  them with categories that fit this research question.
- Add multiple topic-specific knowledge tagging categories that would help later
  extraction. These categories must describe dimensions of knowledge in papers,
  not topical-fit, paper-selection, review-status, confidence, or metadata
  fields.
- Create at least 4 knowledge tagging categories; prefer 5 to 8 when the topic
  has enough reviewable dimensions. A good ontology usually covers several of:
  studied intervention/tool/exposure, population or setting, outcome or target,
  method or study design, measurement or data source, mechanism, claim direction,
  and implementation context.
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
- Give each tagging category multiple allowed values; do not collapse the ontology into one broad category.
- For each category, set `selection` to `single` when at most one value should
  be selected for an applicable paper, or `multi` when several values may be
  selected.
- Set `required` to true only when every applicable paper should receive at
  least one value. Most generated knowledge categories should be optional, and
  optional categories may receive zero values.
- Use `applies_when` to define conditional sub-categories. Use null when the
  category applies generally; otherwise set `category_id` and triggering
  `values` from another category.
- Conditional sub-categories must depend on concrete parent values, not broad
  values like `method`, `outcome`, `population`, or `target`.
- Include `mixed_or_unclear` and `unclear` values where ambiguity is expected.
- Include `not_reported` where missing information is likely.
- Make `scope.include_criteria` cover direct papers and meaningfully adjacent papers.
- Keep `scope.exclude_criteria` for clear mismatches only.
- Make `scope.boundary_rules` describe when related or tangential papers should stay in for human review.
- Make `rule_based_screening.include_terms` broad, atomic, and recall-oriented enough to catch synonyms, adjacent phrasing, plural/singular variants, and common abbreviations or acronyms such as AI/ML/GPA when relevant.
- Do not make `rule_based_screening.include_terms` depend on the generated
  tagging categories. Screening terms should come from the research topic,
  topic structure, and scope.
- Keep `rule_based_screening.exclude_terms` short and only for hard negatives.
- Set candidate screening so borderline or tangentially relevant candidates are included for later review unless clearly outside the topic.
- Include reviews unless the research question explicitly asks for primary studies only.
- Add 4 to 8 `collection.search_queries`; each query should search a different phrasing, synonym set, population, method, application, or adjacent angle.
- Search queries should be precise enough for OpenAlex but not so narrow that useful candidate papers disappear.
- Return JSON matching the schema. For `tagging.categories`, return an array of
  category objects with `category_id`, `description`, `required`, `selection`,
  `values`, and `applies_when`.
