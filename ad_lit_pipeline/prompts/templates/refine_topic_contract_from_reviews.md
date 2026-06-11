You are refining a topic contract for a configurable literature knowledge pipeline.

User research question:
$topic_description

Current topic contract:
$current_contract_json

Extracted review full-text evidence:
$review_overviews_json

Task:
Return a complete refined topic contract. Use only the extracted review
full-text evidence provided here to replace or improve the topic ontology and
knowledge tagging categories so a new user does not need weeks of manual
ontology research before running the pipeline.

Rules:
- Define the final topic structure, tagging categories, and allowed values only
  from `full_text_evidence` in the extracted review records. Do not use titles,
  abstracts, query metadata, citation metadata, or imagined primary papers to
  define tags.
- Do not use titles, abstracts, query metadata, citation metadata, or imagined
  primary papers to define tagging categories or allowed values.
- Define tagging categories and allowed values only from `full_text_evidence`.
- If no extracted review full-text evidence is available, the pipeline should
  fail before this prompt is called. Do not invent a fallback ontology from the
  research question or discovery contract alone.
- Do not let off-topic passages in a review reshape the ontology, even if the
  review itself was selected by the search step.
- Preserve the research question, broad discovery scope, rule-based screening,
  candidate-screening policy, provider settings, and search queries. This task
  may refine only `topic_structure` and `tagging.categories`.
- Keep `collection.allowed_providers` to the providers already in the contract.
- In the JSON response, return `topic_structure.secondary_topics` as an array of
  grouped secondary objects. Each object must include the parent `main_topic_id`
  it can replace, plus `secondary_topic_id`, `label`, `field`, `terms`,
  `retrieval_terms`, and `matching_terms`.
- Rebuild or keep `topic_structure` based on the review full-text evidence:
  - `anchor_topic_id` is the mandatory core concept for title screening. A
    paper title must show this topic to enter the collection.
  - The anchor should be broad enough to catch synonyms, abbreviations, and
    close wording, but not so broad that unrelated papers enter.
  - `main_topics` are the compact, evidence-derived research dimensions of the
    topic. They are the major components a paper can primarily focus on, such
    as a tool/intervention/exposure family, population/context, outcome/target,
    setting, evidence signal, mechanism, or measurement dimension.
  - Use at least 2 main topics; prefer 3 to 6 when the review evidence supports
    them. Each `topic_id` must be lowercase snake_case and compact enough to be
    useful as a tag value.
  - Each main topic must include `field`, `terms`, `retrieval_terms`, and
    `matching_terms`.
  - Set `field` to `title`, `abstract`, or `title_or_abstract` depending on
    where that topic should be required during provider-side retrieval.
  - Set `retrieval_terms` to the strongest provider-search terms for that
    topic, with at most 12 terms. Keep these compact and high-signal.
  - Set `matching_terms` to broader local-matching terms that explain returned
    papers, including useful synonyms, abbreviations, subtypes, and concrete
    indicators.
  - Do not use generic main topics such as `method`, `outcome`, `population`,
    `technology`, `setting`, or `target` unless the id is made
    topic-specific.
  - `secondary_topics` are replacement terms for non-anchor main topics when
    paper titles use adjacent wording. They should improve recall without weakening topical fit,
    and must not be defined for the anchor.
  - Keep different replacement concepts in separate secondary groups. For
    example, higher education and workplace learning are two groups, not one
    mixed secondary-topic term list.
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
- Do not create a root focus selector. Tag papers directly with topic-specific
  categories and values.
- Tag papers directly with topic-specific categories.
- Do not create a whole-question category such as `effect_of_x`; represent
  topic-specific knowledge dimensions directly instead.
- Do a mental distribution check against the seed reviews and the likely primary
  papers they describe: each value in each general category should be useful
  for at least one paper. Do not include values that are merely possible but not
  supported by the review evidence.
- Use `topic_structure.main_topics` as ontology scaffolding: main topic
  components may become direct categories, while matching categories contain
  the concrete ways those components are studied. Rename, split, or merge topic
  components only when the review full text shows a clearer evidence-derived
  structure.
- Prefer a compact ontology: broadly applicable topic categories first, then
  any narrower conditional categories.
- Create conditional sub-categories when a question only makes sense for one
  parent category value. Do not ask every paper for details that only exist
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
  matter, create separate categories with topic-specific ids and concrete
  review-derived values.
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
  direct topic categories and selected conditional categories with
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
  missing, make the category conditional or optional instead.
- Keep category value lists small enough for consistent tagging, usually 4 to 12
  values.
- Every category and every value should help compare papers or reveal a
  meaningful pattern in this specific literature.
- Return JSON matching the schema. For `tagging.categories`, return an array of
  category objects with `category_id`, `description`, `required`, `selection`,
  `values`, and `applies_when`.
