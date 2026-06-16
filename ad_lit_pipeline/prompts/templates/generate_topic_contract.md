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
    These are the compact ontology dimensions that guide screening and later
    topic-specific tagging. Each main topic must represent exactly one
    conceptual area. Do not combine two required areas into one main topic id,
    label, or term list. For example, use separate `ai`, `school`, and
    `student_performance` blocks instead of `ai_in_school`,
    `school_ai_performance`, or `ai_and_student_performance`. When the question
    has distinct intervention/tool/exposure, population/context, outcome/target,
    mechanism, setting, or measurement components, split those into separate
    main topics. Each must have `topic_id`, `label`, `field`, broad `terms`,
    `retrieval_terms`, and `matching_terms`.
  - For each main topic, set `field` to one of `title`, `abstract`, or
    `title_or_abstract`. Generated main topics should default to `title`.
    Use `title_or_abstract` only for detail or explanatory dimensions that can
    be absent from the title without weakening collection relevance, such as
    mechanisms, validation, workflows, measurement details, implementation
    details, or explanatory processes. Do not use `abstract` for generated main
    topics.
  - For each main topic, set `retrieval_terms` to the strongest provider-search
    terms for that topic. Use at most 12 terms. These should be precise enough
    for retrieval and may be shorter than the full synonym list.
  - For each main topic, set `matching_terms` to the broader local-matching
    terms used to explain why a returned paper matched. Include useful
    synonyms, abbreviations, subtypes, and concrete indicators. This list may
    be broader than `retrieval_terms`.
  - `secondary_topics`: an array of secondary group objects. Each object must
    name the parent `main_topic_id` it can replace, plus its own
    `secondary_topic_id`, `label`, `field`, `terms`, `retrieval_terms`, and
    `matching_terms`.
    Every main topic, including the anchor, must have at least one secondary
    group when a clean adjacent sibling direction exists. Secondary groups
    provide neighboring directions for broader discovery, not internal subtypes
    or duplicates of the parent. Each secondary group must name exactly one
    adjacent concept, and its `terms`, `retrieval_terms`, and `matching_terms`
    must be aliases, variants, types, abbreviations, or surface forms of that
    one secondary concept.
- Choose the anchor topic as the mandatory core concept for title screening: a
  title must show this concept to enter the collection. Make it broad enough to
  catch synonyms and abbreviations, but not so broad that unrelated papers enter.
- For questions like "Could X be used to..." or "Use of X in/for...", choose
  X as the anchor when X is the proposed source, tool, intervention, material,
  disease, exposure, or core phenomenon. Do not anchor on the application,
  outcome, or replacement/comparator goal if papers about that goal without X
  would be off-topic.
- Choose main topics as compact terms or directions, not full sentences or
  generic metadata buckets. Good shapes include a tool/intervention family,
  population/context, outcome/target, setting, evidence signal, mechanism, or
  measurement dimension that a paper could primarily focus on.
- Main topic IDs must be short, stable, semantic component names. They must not
  be whole-question labels or merged relationship labels. Good examples:
  `ai`, `school`, `student_performance`, `computational_methods`,
  `alzheimers_disease`. Bad examples: `ai_in_school`,
  `ai_for_student_performance`, `computational_methods_for_alzheimer_research`.
- Terms inside a main topic must name only that one component. If `school` is a
  separate main topic, do not put `AI in schools` in the `ai` terms. Put `AI`
  terms under `ai` and school-setting terms under `school`.
- Terms inside a main topic must include the in-family surface forms for that
  main topic: types, variants, subcategories, versions, stages, other names,
  abbreviations, common synonyms, and narrower indicators that still belong to
  the same family. Do not move these in-family forms into secondary topics.
- Do not use broad background words as topic terms when specific vocabulary is
  available. Avoid standalone terms like `education`, `learning environment`,
  `educational settings`, `performance metrics`, `technology`, `tools`,
  `educational technology`, `digital technology`, `outcomes`, or `students`;
  prefer concrete phrases such as `school`, `classroom`, `K-12`,
  `academic achievement`, or the equivalent specific terms for the user's
  domain.
- Avoid broad umbrella terms in `terms` and `retrieval_terms`, such as `data
  analysis`, `neurological disorder`, `disease`, `condition`, `method`,
  `approach`, `science`, or `technology`, unless that exact umbrella is the
  named component itself.
- A good main-topic decomposition usually maps to necessary parts of the
  research question: intervention/tool/exposure, population/setting/context,
  outcome/target, disease/phenomenon, method family, measurement, or evidence
  signal. Use only the components that are truly necessary for relevance.
- Do not use a broad criterion or motivation, such as sustainability,
  environmental impact, green, eco-friendly, or renewable, as a required main
  topic when the question names a more concrete replacement, comparator,
  material, application, or use case. Put the concrete concept in
  `main_topics`; keep broad criteria in scope, screening, or later tagging.
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
  wording in the main topic id/label. Put inferred nearby wording in secondary
  topics. For example, use `building_materials` as the main topic when the user
  says building materials; use `construction_products` or `building_products`
  as secondary groups.
- Keep application/domain topics concrete. Avoid generic terms like
  `innovative materials`, `materials science`, `construction technology`,
  `advanced materials`, or broad sustainability criteria unless the phrase is
  the exact named domain in the user's question.
- Terms and matching terms for application/domain topics should name the use
  area, product family, setting, or domain. Do not use property, process, or
  evaluation phrases such as `structural integrity`, `construction
  innovations`, `building techniques`, `effective products`, or `responsible
  practices` unless that property/process is the actual research object.
- Secondary groups for application/domain topics must also be application
  wording, not criteria. For building-material topics, use groups such as
  `construction_products`, `building_products`, `structural_materials`, or
  `insulation_materials`; do not use `eco_friendly_materials`,
  `green_alternatives`, `renewable_materials`, or sustainability criteria.
- If the user explicitly names multiple outcomes, targets, signals, or
  phenomena joined by `and`, split them into separate main topics when each is
  a meaningful required concept. For example, a topic about attention and
  memory should use separate `attention` and `memory` main topics instead of
  hiding both under `cognitive_effects`.
- Prefer 3 to 6 main topics when the research question and vocabulary support
  that many, but never use fewer than 2. Avoid creating so many main topics
  that screening and tagging categories become inconsistent.
- The main topic ids should be stable lowercase snake_case ids because later
  categories may use those ids directly.
- Later tagging categories may use those ids directly, so avoid changing them
  casually once a good decomposition exists.
- Use secondary topics as adjacent sibling directions for each main topic when
  titles use neighboring concepts. Secondary topics should improve recall
  without weakening topical fit.
- For every main topic, including the anchor, add useful secondary-topic groups
  when the topic has genuinely adjacent sibling directions. Secondary topics
  must be adjacent concepts in the same broad kind of thing as the parent, but
  not related as versions, aliases, variants, types, subcategories, examples,
  or narrower subtypes of the parent. For example, `parkinsons_disease` or
  `cancer` may be adjacent sibling disease directions for an
  `alzheimers_disease` parent, while dementia, cognitive decline, MCI, mild
  cognitive impairment, prodromal disease, and preclinical disease belong in
  the Alzheimer's disease parent terms. Likewise, `machine_learning` and
  `deep_learning` are internal parts of `computational_methods` and belong in
  the parent terms.
- Do not create vague secondary buckets such as `related_diseases`,
  `other_diseases`, or `dementia_types`. Use one secondary group per adjacent
  concept. For example, use a `parkinsons_disease` group with terms such as
  Parkinson's disease, Parkinson disease, and PD, and a separate `cancer`
  group with terms such as cancer, neoplasm, and tumor. Do not put generic
  descriptors such as `dementia types`, `neurodegenerative diseases`, or
  `cognitive impairments` in a secondary group's term lists.
- For computational-method parents, use adjacent non-computational method
  families such as `experimental_methods`, `laboratory_methods`, or
  `clinical_methods` as secondary topics when a secondary is needed. Do not use
  AI, ML, deep learning, supervised learning, unsupervised learning,
  statistical modeling, network analysis, or systems biology as secondary
  topics for computational methods; those belong in the parent terms.
- Keep secondary replacements as separate semantic groups. Do not mix different
  fallback concepts into one group. For example, for a `school_setting` main
  topic, use one secondary group for higher education terms and another
  secondary group for workplace-learning terms.
- Make main topics broad enough for title screening. Prefer general component
  labels such as intervention family, tool family, population/context, outcome
  family, exposure, or domain over narrow phrases from the user's exact wording.
  For example, use a broad app/digital-intervention component rather than a
  single exact product or phrase when the literature may use many labels.
- Make main-topic `terms` and `matching_terms` broad enough for local matching:
  include true synonyms, common abbreviations, subtypes, concrete
  platforms/tools, and narrower indicators that still represent the same topic
  component. Each main topic should usually have at least 6 matching terms when
  the domain vocabulary supports that many. Include singular/plural variants
  only when they help retrieval.
- Main-topic terms should include common in-family categories, subtopics,
  applications, methods, concepts, components, and properties when they remain
  inside the same subject area. For a method topic such as
  `computational_methods`, include terms such as machine learning, ML, deep
  learning, supervised learning, unsupervised learning, statistical modeling,
  network analysis, systems biology, and other common computational submethods
  when relevant.
- Do not put bare domain/object terms inside method topics. Prefer qualified
  method phrases such as computational genomics, genomic analysis, or
  bioinformatics analysis; avoid bare terms such as genomics, biomarkers,
  amyloid plaques, tau tangles, or patient cohorts as method-topic terms.
- For disease or condition main topics, include common in-family disease names,
  abbreviations, variants, stages, subtypes, and related impairment states in
  the parent terms when they are part of the same disease area. Use secondary
  topics for neighboring disease/application directions, not for variants that
  belong inside the parent disease family.
- Include commonly used surface forms explicitly when they matter: abbreviations
  and full forms such as `AI` and `artificial intelligence`, spelling or
  punctuation variants such as `A.I.` when common in the literature, and common
  synonyms. Do not add rare, invented, or merely capitalization-only variants.
- For broad components such as AI, fungi/mycelium, Alzheimer disease,
  computational methods, school settings, or building materials, provide at
  least 4 focused `terms` and usually 6 or more `matching_terms` when the
  vocabulary supports it.
- Do not pad term lists with broad background words. More terms are useful only
  when they remain inside the same conceptual area.
- Make `retrieval_terms` compact and high-signal. Never include more than 12
  retrieval terms for one topic.
- Keep `retrieval_terms` component-pure. Do not include phrases that mix this
  topic with another main topic, such as `educational AI` when `ai` and
  `school` are separate blocks.
- Set the anchor main topic's `field` to `title`. Default every generated main
  topic to `title` unless it is a detail or explanatory dimension that can be
  absent from the title without weakening collection relevance, such as a
  mechanism, validation, workflow, measurement detail, implementation detail, or
  explanatory process.
- Do not use `abstract` for generated main topics. If a concept may appear only
  outside titles and is still required for relevance, keep it as a `title`
  main topic with richer terms rather than weakening the field.
- Setting, context, or population components should use `title` whenever they
  are required for relevance.
- Include domain-specific named variants, abbreviations, subtypes, tools, and
  concrete indicators for each component. For example, an AI component should
  include named AI methods/tools when relevant, while a disease component should
  include disease names and abbreviations.
- Avoid making abstract outcome words mandatory title components when papers
  are likely to express that component through concrete outcome names. Put the
  concrete names in the component's terms or in secondary-topic replacements.
- Put related-but-not-same concepts in `secondary_topics`, including for the anchor.
- Secondary topics are controlled adjacent sibling groups for one main
  topic. They should be adjacent sibling directions that go in a different
  direction from the parent, not internal subtypes or examples. If a secondary
  term is an in-family subtype of the parent, move it into the parent terms.
- Parent and secondary term groups must be disjoint across `terms`,
  `retrieval_terms`, and `matching_terms`. Do not repeat parent terms,
  synonyms, or internal subtypes in secondary groups.
- Do not create a secondary topic that simply repeats a parent main-topic term.
  For example, if `academic achievement` is already in
  `student_performance.terms`, do not add an `academic_achievement` secondary
  group under `student_performance`.
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
- Set candidate screening so borderline or tangentially relevant candidates are included for later review unless clearly outside the topic.
- Add 4 to 8 `collection.search_queries`; each query should search a different
  phrasing, synonym set, population, method, application, or adjacent angle.
- Search queries should be precise enough for OpenAlex but not so narrow that
  useful candidate papers disappear.
- Treat any categories in the base contract template as examples only.
- Tagging categories in this first contract are provisional. Create only a
  simple structurally valid tagging section so the contract can pass shape
  validation. Do not spend effort building the final extraction ontology; that
  will be refined from review and overview papers in a later step.
- Include at least one provisional tagging category, but do not create any root
  focus selector. Prefer a simple topic-specific category whose id matches one
  important main topic and whose values are provisional concrete subtypes. The
  final detailed categories and values will be rebuilt from review full text
  later.
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
