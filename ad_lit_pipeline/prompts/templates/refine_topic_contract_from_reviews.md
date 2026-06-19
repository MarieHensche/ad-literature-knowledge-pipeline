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
  it expands with an adjacent sibling direction, plus `secondary_topic_id`,
  `label`, `field`, `terms`, `retrieval_terms`, and `matching_terms`.
- Rebuild or keep `topic_structure` based on the review full-text evidence:
  - `anchor_topic_id` is the mandatory core concept for title screening. A
    paper title must show this topic to enter the collection.
  - For disease-specific method/tool topics such as computational biology
    methods for Alzheimer's disease research, choose the disease as the anchor.
    The disease is non-replaceable; method components can have adjacent method
    secondaries.
  - The anchor should be broad enough to catch synonyms, abbreviations, and
    close wording, but not so broad that unrelated papers enter.
  - For questions like "Could X be used to..." or "Use of X in/for...", choose
    X as the anchor when X is the proposed source, tool, intervention, material,
    disease, exposure, or core phenomenon. Do not anchor on the application,
    outcome, or replacement/comparator goal if papers about that goal without X
    would be off-topic.
  - `main_topics` are the compact, evidence-derived research dimensions of the
    topic. They are the major components a paper can primarily focus on, such
    as a tool/intervention/exposure family, population/context, outcome/target,
    setting, evidence signal, mechanism, or measurement dimension.
  - Each main topic must represent exactly one conceptual area. Do not combine
    two required areas into one main topic id, label, or term list. For example,
    use separate `ai`, `school`, and `student_performance` blocks instead of
    `ai_in_school`, `school_ai_performance`, or
    `ai_and_student_performance`.
  - Main topic IDs must be short, stable, semantic component names. They must
    not be whole-question labels or merged relationship labels. Good examples:
    `ai`, `school`, `student_performance`, `computational_methods`,
    `alzheimers_disease`. Bad examples: `ai_in_school`,
    `ai_for_student_performance`, `computational_methods_for_alzheimer_research`.
  - Do not use a broad criterion or motivation, such as sustainability,
    environmental impact, green, eco-friendly, or renewable, as a required main
    topic when the question names a more concrete replacement, comparator,
    material, application, or use case.
  - If the question says a concept could replace, substitute for, or be an
    alternative to a concrete target, make that target or replacement relation a
    main topic id/label. For example, use `concrete_replacement` or `concrete`,
    not only a broad `building_materials` topic with `concrete` buried in its
    terms.
  - Keep replacement/comparator topics component-pure. Their terms should name
    the target and substitution relation only, such as `concrete replacement`,
    `concrete alternative`, `concrete substitute`, `cement replacement`, or
    `cement substitute`. Do not include application/domain terms such as
    `building materials`, or broad criterion words such as `sustainable`,
    `green`, `eco-friendly`, or `renewable`. Do not use broad material-family
    terms such as `biomaterials`, `biodegradable materials`, or `bio-based
    alternatives` unless they are explicitly tied to the replacement target.
  - If that same question also names an application or domain, keep it as a
    separate main topic instead of folding it into the replacement topic. For
    example, a topic about fungi creating building materials that replace
    concrete should use separate `fungi`, `building_materials`, and
    `concrete_replacement` main topics.
  - When the user explicitly names a valid component phrase, preserve that
    wording in the main topic id/label. Put inferred nearby wording in
    secondary topics. For example, use `building_materials` as the main topic
    when the user says building materials; use `construction_products` or
    `building_products` as secondary groups.
  - Keep application/domain topics concrete. Avoid generic terms like
    `innovative materials`, `materials science`, `construction technology`,
    `advanced materials`, or broad sustainability criteria unless the phrase is
    the exact named domain in the user's question.
  - Terms and matching terms for application/domain topics should name the use
    area, product family, setting, or domain. Do not use property, process, or
    evaluation phrases such as `structural integrity`, `construction
    innovations`, `building techniques`, `effective products`, or `responsible
    practices` unless that property/process is the actual research object.
  - If the user explicitly names multiple outcomes, targets, signals, or
    phenomena joined by `and`, split them into separate main topics when each is
    a meaningful required concept.
  - Terms inside a main topic must name only that one component. If `school` is
    a separate main topic, do not put `AI in schools` in the `ai` terms. Put
    `AI` terms under `ai` and school-setting terms under `school`.
  - Do not use broad background words as topic terms when specific vocabulary
    is available. Avoid standalone terms like `education`, `learning
    environment`, `educational settings`, `performance metrics`, `technology`,
    `educational technology`, `digital technology`, `tools`, `outcomes`, or
    `students`; prefer concrete domain phrases.
  - Avoid broad umbrella terms in `terms` and `retrieval_terms`, such as `data
    analysis`, `neurological disorder`, `disease`, `condition`, `method`,
    `approach`, `science`, or `technology`, unless that exact umbrella is the
    named component itself.
  - Use at least 2 main topics; prefer 3 to 6 when the review evidence supports
    them. Each `topic_id` must be lowercase snake_case and compact enough to be
    useful as a tag value.
  - Each main topic must include `field`, `terms`, `retrieval_terms`, and
    `matching_terms`.
  - For broad components such as AI, fungi/mycelium, Alzheimer disease,
    computational methods, school settings, or building materials, provide at
    least 4 focused `terms` and usually 6 or more `matching_terms` when the
    vocabulary supports it. Do not pad term lists with broad background words.
  - Set `field` to `title`, `abstract`, or `title_or_abstract`. Default every
    generated main topic to `title` unless it is a detail or explanatory
    dimension that can be absent from the title without weakening collection
    relevance, such as a mechanism, validation, workflow, measurement detail,
    implementation detail, or explanatory process.
  - Set the anchor main topic's `field` to `title`.
  - Do not use `abstract` for generated main topics. If a concept may appear
    only outside titles and is still required for relevance, keep it as a
    `title` main topic with richer terms rather than weakening the field.
  - Setting, context, or population components should use `title` whenever they
    are required for relevance.
  - Include domain-specific named variants, abbreviations, subtypes, tools, and
    concrete indicators for each component.
  - Terms inside a main topic must include in-family surface forms for that
    main topic: types, variants, subcategories, versions, stages, other names,
    abbreviations, common synonyms, and narrower indicators that still belong
    to the same family. Do not move these in-family forms into secondary
    topics.
  - Main-topic terms should include common in-family categories, subtopics,
    applications, methods, concepts, components, and properties when they remain
    inside the same subject area. For a method topic such as
    `computational_methods`, include terms such as machine learning, ML, deep
    learning, supervised learning, unsupervised learning, statistical modeling,
    network analysis, systems biology, and other common computational
    submethods when relevant.
  - Do not put bare domain/object terms inside method topics. Prefer qualified
    method phrases such as computational genomics, genomic analysis, or
    bioinformatics analysis; avoid bare terms such as genomics, biomarkers,
    amyloid plaques, tau tangles, or patient cohorts as method-topic terms.
  - For disease or condition main topics, include common in-family disease
    names, abbreviations, variants, stages, subtypes, and related impairment
    states in the parent terms when they are part of the same disease area.
    For Alzheimer's disease, this can include MCI, prodromal disease,
    preclinical disease, dementia, or dementia-related cognitive impairment
    when relevant. Use secondary topics for neighboring disease/application
    directions, not for variants that belong inside the parent disease family.
  - For disease or condition main topics, do not put pathology, mechanism,
    biomarker, symptom, or process terms in the topic term lists. For
    Alzheimer's disease, terms such as tau pathology, amyloid plaques,
    neurodegeneration, or memory loss are not disease-family names; keep them
    for scope, screening, or later tagging categories.
  - Include commonly used surface forms explicitly when they matter:
    abbreviations and full forms such as `AI` and `artificial intelligence`,
    spelling or punctuation variants such as `A.I.` when common in the
    literature, and common synonyms. Do not add rare, invented, or merely
    capitalization-only variants.
  - Set `retrieval_terms` to the strongest provider-search terms for that
    topic, with at most 12 terms. Keep these compact and high-signal.
  - Keep `retrieval_terms` component-pure. Do not include phrases that mix this
    topic with another main topic, such as `educational AI` when `ai` and
    `school` are separate blocks.
  - Set `matching_terms` to broader local-matching terms that explain returned
    papers, including useful synonyms, abbreviations, subtypes, and concrete
    indicators.
  - Do not use generic main topics such as `method`, `outcome`, `population`,
    `technology`, `setting`, or `target` unless the id is made
    topic-specific.
  - `secondary_topics` are adjacent sibling directions for main topics when
    paper titles use neighboring concepts. They should improve recall without weakening topical fit
    and should also be defined for the anchor when there are clean adjacent
    directions.
  - Add useful secondary-topic groups for every main topic, including the
    anchor, when the review evidence shows genuinely adjacent sibling directions.
    Secondary topics must be adjacent concepts in the same broad
    kind of thing as the parent, but not related as versions, aliases,
    variants, types, subcategories, examples, or narrower subtypes of the
    parent. For example, `parkinsons_disease` or `cancer` may be adjacent
    sibling disease directions for an `alzheimers_disease` parent, while
    dementia, cognitive decline, MCI, mild cognitive impairment, prodromal
    disease, and preclinical disease belong in the Alzheimer's disease parent
    terms. Likewise, `machine_learning` and `deep_learning` are internal parts
    of `computational_methods` and belong in the parent terms.
  - Each secondary group must name exactly one adjacent concept, and its
    `terms`, `retrieval_terms`, and `matching_terms` must be aliases,
    variants, types, abbreviations, or surface forms of that one secondary
    concept. Do not create vague secondary buckets such as `related_diseases`,
    `other_diseases`, or `dementia_types`. For example, use a
    `parkinsons_disease` group with terms such as Parkinson's disease,
    Parkinson disease, and PD, and a separate `cancer` group with terms such
    as cancer, neoplasm, and tumor. Do not put generic descriptors such as
    `dementia types`, `neurodegenerative diseases`, or `cognitive impairments`
    in a secondary group's term lists.
  - For computational-method parents, use adjacent non-computational method
    families such as `experimental_methods`, `laboratory_methods`, or
    `clinical_methods` as secondary topics when a secondary is needed. Do not
    use AI, ML, deep learning, supervised learning, unsupervised learning,
    statistical modeling, network analysis, or systems biology as secondary
    topics for computational methods; those belong in the parent terms.
  - Parent and secondary term groups must be disjoint across `terms`,
    `retrieval_terms`, and `matching_terms`. Do not repeat parent terms,
    synonyms, or internal subtypes in secondary groups.
  - Do not create a secondary topic that simply repeats a parent main-topic
    term. For example, if `academic achievement` is already in
    `student_performance.terms`, do not add an `academic_achievement` secondary
    group under `student_performance`.
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
