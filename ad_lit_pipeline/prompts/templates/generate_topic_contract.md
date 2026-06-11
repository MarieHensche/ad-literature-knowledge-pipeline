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
    topic-specific tagging. When the question has distinct
    intervention/tool/exposure, population/context, outcome/target, mechanism,
    setting, or measurement components, split those into separate main topics.
    Each must have `topic_id`, `label`, `field`, broad `terms`,
    `retrieval_terms`, and `matching_terms`.
  - For each main topic, set `field` to one of:
    - `title` when the topic must be visible in the title for high-precision
      retrieval.
    - `abstract` when the topic is important but often appears only in the
      abstract.
    - `title_or_abstract` when either field is acceptable.
    Use only `title`, `abstract`, or `title_or_abstract`.
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
    Use non-anchor main topic ids only. Do not define secondary replacements for
    the anchor.
- Choose the anchor topic as the mandatory core concept for title screening: a
  title must show this concept to enter the collection. Make it broad enough to
  catch synonyms and abbreviations, but not so broad that unrelated papers enter.
- Choose main topics as compact terms or directions, not full sentences or
  generic metadata buckets. Good shapes include a tool/intervention family,
  population/context, outcome/target, setting, evidence signal, mechanism, or
  measurement dimension that a paper could primarily focus on.
- Prefer 3 to 6 main topics when the research question and vocabulary support
  that many, but never use fewer than 2. Avoid creating so many main topics
  that screening and tagging categories become inconsistent.
- The main topic ids should be stable lowercase snake_case ids because later
  categories may use those ids directly.
- later categories may use those ids directly.
- Use secondary topics only as replacement wording for non-anchor main topics
  when titles use adjacent language. Secondary topics should improve recall
  without weakening topical fit.
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
- Each main topic should usually have at least 6 terms across `terms` and
  `matching_terms` when the domain vocabulary supports that many.
- Make `retrieval_terms` compact and high-signal. Never include more than 12
  retrieval terms for one topic.
- Avoid making abstract outcome words mandatory title components when papers
  are likely to express that component through concrete outcome names. Put the
  concrete names in the component's terms or in secondary-topic replacements.
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
