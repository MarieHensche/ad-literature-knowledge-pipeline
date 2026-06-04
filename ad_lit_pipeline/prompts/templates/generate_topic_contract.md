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
- Create at least 6 knowledge tagging categories; prefer 6 to 10 when the topic
  has enough reviewable dimensions.
- Category IDs and allowed values must use lowercase snake_case. Do not return
  labels with spaces, slashes, punctuation, or title case.
- The first tagging category must have category_id `knowledge_goal`, required
  true, selection `single`, and applies_when null.
- `knowledge_goal` values must form a complete, mutually exclusive partition of
  the included papers for this topic. This is the main knowledge axis, similar
  to a research goal, intervention aim, application type, or phenomenon type.
  Do not copy these example values; infer the actual values from the topic.
- `knowledge_goal` values must be role-like nouns or noun phrases, not vague
  benefit/action phrases. Bad shapes include `improving_x`, `enhancing_y`,
  `supporting_z`, `studying_x`, or `evaluating_y` because they usually absorb
  most papers. Prefer partition values like prevention, screening_detection,
  treatment_effectiveness, implementation_acceptability, diagnosis, prognosis,
  intervention_response, or other review-derived role values when they fit.
- Every `knowledge_goal` value should plausibly receive at least one paper in a
  normal run for this topic, and no single value should be so broad that it
  would absorb almost all papers. If one value would dominate, split that value
  into more meaningful knowledge-goal values or choose a better root axis.
- Do a mental distribution check before returning the ontology: for the likely
  papers retrieved by the main topics and search queries, each value in each
  general category should be useful for at least one paper. Do not include
  values that are merely possible but unlikely to occur.
- Use `topic_structure.main_topics` as scaffolding for `knowledge_goal`: the
  values should describe the main knowledge roles papers play around those
  topic components, not topical-fit labels and not metadata. Do not simply copy
  main topic IDs unless they are truly the best knowledge-goal values.
- The top-level partition values should be concrete and exhaustive for the
  topic, not `unclear`, `not_reported`, `other`, or metadata placeholders.
- Prefer a small hierarchy: broad required root category first, then
  conditional sub-categories that apply only for specific `knowledge_goal`
  values.
- Create conditional sub-categories when a question only makes sense for one
  `knowledge_goal` value. Do not ask every paper for details that only exist
  for a subset of papers.
- A required conditional category must be answerable for every paper that
  matches its `applies_when` parent value.
- Keep values within a single-selection category mutually exclusive. If values
  can co-occur, make the category multi-selection or split the category.
- A good ontology usually covers several topic-specific dimensions such as:
  studied intervention/tool/exposure, domain population or setting, outcome or
  target, analytic approach, evidence signal, measurement, mechanism, claim
  direction, and implementation context.
- Do not add generic method or participant buckets just because papers have
  methods and participants. A design, population, or data-source category must
  use a topic-specific id and values grounded in the research question.
- Each category must be a concrete question that can be answered directly from
  a paper, such as what intervention, method, population, setting, outcome,
  mechanism, data source, measurement, or claim type the paper reports.
- Each category description must briefly state why the category is relevant for
  this topic based on the research question or review evidence.
- Do not create meta-categories whose values are other category types. Avoid
  category IDs such as `knowledge_dimension`, `tag_type`, `evidence_kind`,
  `paper_focus`, `research_area`, or `category`.
- Do not use values such as `method`, `outcome`, `population`, `equity`, or
  `target` as a substitute for separate concrete categories. If those concepts
  matter, create separate categories like `ai_tool_type`,
  `performance_outcome`, `student_group`, `education_setting`,
  `equity_dimension`, or another topic-specific method/design category.
- Do not add generic boilerplate categories such as `study_design`,
  `study_population`, `population_group`, `target_population`,
  `data_source_type`, or `study_type`. If such a distinction is truly central,
  use a topic-specific category id and values, such as
  `clinical_trial_design`, `noise_exposure_population`, `school_level`,
  `perinatal_care_stage`, or another review-derived label.
- Give each tagging category multiple allowed values; do not collapse the ontology into one broad category.
- For each category, set `selection` to `single` when at most one value should
  be selected for an applicable paper, or `multi` when several values may be
  selected.
- Set `required` to true only when every applicable paper must receive at least
  one concrete value from a complete value set. Usually this includes the main
  root partition category and selected conditional categories with
  `applies_when`; optional categories may receive zero values.
- Use `applies_when` to define conditional sub-categories. Use null when the
  category applies generally; otherwise set `category_id` and triggering
  `values` from another category.
- Conditional sub-categories must depend on concrete parent values, not broad
  values like `method`, `outcome`, `population`, or `target`.
- Do not add `unclear`, `mixed_or_unclear`, `not_reported`, or `other` as
  values in newly generated knowledge categories. If a value would often be
  missing, make the category conditional or optional instead. If the top-level
  root category feels unclear, choose a better exhaustive partition.
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
