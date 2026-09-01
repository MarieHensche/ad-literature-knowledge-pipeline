You are refining a topic contract for a configurable literature knowledge
pipeline.

User research question:
$topic_description

Current topic contract:
$current_contract_json

Extracted review full-text evidence:
$review_overviews_json

Versioned topic-structure policy guidance:
$topic_policy_guidance

Task:
Return a complete refined contract. Build final tagging categories only from
the supplied `full_text_evidence`. You may refine only `topic_structure` and
`tagging.categories`; preserve the research topic, scope, screening policies,
provider settings, corpus specification, search queries, and fallback policy.

Evidence rules:
- Define tagging categories and allowed values only from `full_text_evidence`.
  Do not use titles, abstracts, query metadata, citation metadata, the bootstrap
  categories, or imagined primary papers as ontology evidence.
- If no extracted review full-text evidence is available, do not invent an
  ontology. The caller should fail before this prompt is used.
- Ignore off-topic passages even when their review was selected for discovery.
- Category descriptions briefly identify the review-evidence distinction that
  motivates the category.

Topic-structure rules:
- `anchor_topic_id` is the mandatory non-replaceable title-screening concept.
  Set its main-topic field to `title`.
- For questions like "Could X be used to..." or "Use of X in/for...", anchor
  on X when papers about the application or outcome without X would be
  off-topic.
- Use at least two main topics, normally three to six when evidence supports
  them. Each main topic represents exactly one conceptual area; never use a
  whole-question or merged relationship id.
- Keep ids short, stable, semantic, and lowercase snake_case. Preserve explicit
  valid user component wording.
- Terms inside a main topic name only that component. Split independently
  required tools, interventions, exposures, populations, contexts, outcomes,
  targets, settings, mechanisms, measurements, and evidence signals.
- Do not substitute a broad criterion or motivation for a concrete comparator,
  replacement target, material, application, or use case. Keep an explicitly
  named target and application/domain as separate component-pure main topics.
- Each main topic includes `field`, `terms`, `retrieval_terms`, and
  `matching_terms`. Include at least four focused terms and normally six or more
  matching terms when the evidence supports real vocabulary. Do not pad lists.
- Retrieval terms are high-signal, component-pure, and limited to twelve.
  Matching terms may be broader but remain in the same concept.
- Default generated fields to `title`; use `title_or_abstract` only for an
  explanatory detail that may be absent from titles without weakening topical
  relevance. Never use abstract-only generated topics. Required setting,
  context, and population components use `title`.
- Return `secondary_topics` as grouped objects containing `main_topic_id`,
  `secondary_topic_id`, `label`, `field`, `terms`, `retrieval_terms`, and
  `matching_terms`.
- Add a secondary group for every main topic when review evidence supports a
  clean adjacent sibling. A secondary is not an alias, version, stage, variant,
  example, or internal subtype of its parent.
- Each secondary group names one adjacent concept and contains only that
  concept's aliases and surface forms. Keep parent and secondary term sets
  disjoint; do not create vague related/other buckets or repeat a parent term.
- Apply the supplied versioned policy guidance exactly. It is the only source
  for configured concept-specific completion, exclusion, fallback, common
  surface-form, and anchor-precedence rules.

Final tagging ontology rules:
- Treat all bootstrap categories as replaceable examples. Build final tagging
  categories only from extracted review full-text evidence.
- Create at least six topic-specific knowledge categories, normally six to ten
  when evidence supports them. Cover distinct paper-answerable dimensions such
  as the studied intervention/tool/exposure, topic-specific population or
  setting, outcome or target, analytic approach, signal or measurement,
  mechanism, claim direction, or implementation context.
- Do not create a root focus selector, whole-question category, metadata
  category, review status, confidence category, generic method/participant
  bucket, or category whose values are other category types.
- Every category must be useful across multiple papers and directly answerable
  from an individual paper. Do not create author, journal, title, or
  single-paper values.
- Use compact lowercase snake_case category ids and values. Provide multiple
  concrete allowed values for every category.
- Use `selection: single` only when values are mutually exclusive; otherwise
  use `multi` or split the category.
- Use `required: true` only when every applicable paper can receive one of a
  complete set of concrete values.
- Use conditional sub-categories only when the question applies to a defined
  parent value. Every `applies_when` reference and trigger value must exist.
- Run a mental distribution check against the review evidence. Remove values
  that are merely possible, duplicate another value, are too broad, or have no
  evidence support.
- Do not add `unclear`, `mixed_or_unclear`, `not_reported`, `other`, or similar
  catch-all values. Missing-information behavior belongs in fallback policy.

Return only strict JSON matching the complete topic-contract schema.
