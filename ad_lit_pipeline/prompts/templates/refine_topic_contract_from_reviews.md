You are refining a topic contract for a configurable literature knowledge pipeline.

User research question:
$topic_description

Current topic contract:
$current_contract_json

Extracted review full-text evidence:
$review_overviews_json

Task:
Return a complete refined topic contract. Use only the extracted review
full-text evidence provided here to replace or improve the knowledge tagging
categories so a new user does not need weeks of manual ontology research before
running the pipeline.

Rules:
- Define tagging categories and allowed values only from `full_text_evidence` in
  the extracted review records. Do not use titles, abstracts, query metadata,
  citation metadata, or imagined primary papers to define tags.
- If no extracted review full-text evidence is available, the pipeline should
  fail before this prompt is called. Do not invent a fallback ontology from the
  research question or discovery contract alone.
- Do not let off-topic passages in a review reshape the ontology, even if the
  review itself was selected by the search step.
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
- The current contract prompt context intentionally omits bootstrap categories.
  Build final categories from extracted review full-text evidence, not from
  provisional discovery placeholders.
- Add or improve multiple topic-specific knowledge categories for what the
  literature is about: targets, phenomena, populations, outcomes, mechanisms,
  claims, signals, methods, or other domain concepts visible in the review
  evidence.
- The first tagging category must have category_id `knowledge_goal`, required
  true, selection `single`, and applies_when null.
- Treat `knowledge_goal` as the primary study-focus or primary knowledge
  contribution partition for the relevant papers. Its values must form a
  complete, mutually exclusive root axis for what each paper is mainly about.
  The id stays `knowledge_goal` for pipeline compatibility, but the category is
  conceptually the paper's primary study focus.
- `knowledge_goal` values must be role-like nouns or noun phrases grounded in
  the selected review full texts, not vague benefit/action phrases. Bad shapes
  include `improving_x`, `enhancing_y`, `supporting_z`, `studying_x`, or
  `evaluating_y` because they usually absorb most papers. Prefer concrete
  topic-derived focus values such as intervention_effect,
  mechanism_explanation, measurement_validation, implementation_barrier,
  population_difference, tool_application, or other evidence-derived study
  focus values when they fit. Do not copy these examples.
- Every `knowledge_goal` value should plausibly receive at least one paper in a
  normal run for this topic, and no single value should be so broad that it
  would absorb almost all papers. If one review-derived value would dominate,
  split that value into more meaningful knowledge-goal values or choose a
  better root axis from the review evidence.
- Do a mental distribution check against the seed reviews and the likely primary
  papers they describe: each value in each general category should be useful
  for at least one paper. Do not include values that are merely possible but not
  supported by the review evidence.
- Use `topic_structure.main_topics` as scaffolding for `knowledge_goal`: the
  values should describe the main knowledge roles papers play around those
  topic components, not topical-fit labels and not metadata. Do not simply copy
  main topic IDs unless they are truly the best knowledge-goal values.
- The top-level partition values should cover all papers in the topic and be
  concrete. Do not use `unclear`, `not_reported`, `other`, or metadata
  placeholders as values.
- Prefer a compact hierarchy: broad required root category first, then
  conditional sub-categories that apply only for specific `knowledge_goal`
  values.
- Create conditional sub-categories when a question only makes sense for one
  `knowledge_goal` value. Do not ask every paper for details that only exist
  for a subset of papers.
- A required conditional category must be answerable for every paper that
  matches its `applies_when` parent value.
- Keep values within a single-selection category mutually exclusive. If values
  can co-occur, make the category multi-selection or split the category.
- Create at least 6 knowledge tagging categories; prefer 6 to 10 when the review
  evidence supports it. A good ontology usually covers several topic-specific
  dimensions such as: studied intervention/tool/exposure, domain population or
  setting, outcome or target, analytic approach, evidence signal, measurement,
  mechanism, claim direction, and implementation context.
- Do not add generic method or participant buckets just because papers have
  methods and participants. A design, population, or data-source category must
  use a topic-specific id and values grounded in the review evidence.
- Do not add categories for topical fit, paper selection, review status,
  confidence, extraction basis, paper metadata, authors, journals, or single
  paper titles.
- Each category must be a concrete question that can be answered directly from
  a paper, such as what intervention, method, population, setting, outcome,
  mechanism, data source, measurement, or claim type the paper reports.
- Each category description must briefly state which review evidence or
  topic-specific distinction motivated the category.
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
- Give each tagging category multiple allowed values; do not collapse the
  ontology into one broad category.
- Prefer compact category IDs in lowercase snake_case.
- Prefer compact allowed values in lowercase snake_case.
- Category IDs and allowed values must use lowercase snake_case. Do not return
  labels with spaces, slashes, punctuation, or title case.
- Keep each category useful across many papers, not just one seed review.
- Do not create values for author names, journal names, or single paper titles.
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
- If a category only applies after another category has a specific value, that
  relationship must be represented in `applies_when`.
- Conditional sub-categories must depend on concrete parent values, not broad
  values like `method`, `outcome`, `population`, or `target`.
- Do not add `unclear`, `mixed_or_unclear`, `not_reported`, or `other` as
  values in newly generated knowledge categories. If a value would often be
  missing, make the category conditional or optional instead. If the top-level
  root category feels unclear, choose a better exhaustive partition.
- Keep category value lists small enough for consistent tagging, usually 4 to 12
  values.
- Return JSON matching the schema. For `tagging.categories`, return an array of
  category objects with `category_id`, `description`, `required`, `selection`,
  `values`, and `applies_when`.
