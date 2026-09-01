You are drafting a bootstrap topic contract for a configurable literature
knowledge pipeline.

User research question:
$topic_description

Base contract template:
$base_contract_json

Versioned topic-structure policy guidance:
$topic_policy_guidance

Task:
Return a complete discovery-focused topic contract for the research question.
This first contract finds relevant review and overview papers. Its tagging
categories are provisional; a later review-evidence step builds the final
extraction ontology.

Topic-structure rules:
- Set `topic_id` and every semantic id to compact lowercase snake_case.
- `topic_structure.anchor_topic_id` must name one main topic: the mandatory,
  non-replaceable core concept for title screening. Set its field to `title`.
- For questions like "Could X be used to..." or "Use of X in/for...", choose X
  as the anchor when papers about the application or outcome without X would be
  off-topic. Do not anchor on a replaceable destination or outcome.
- Use at least two main topics, normally three to six when the question supports
  them. Each main topic must represent exactly one conceptual area. Do not use a
  whole-question id or merge required components into one topic.
- Main-topic ids and labels must be short, stable component names. Categories
  may use those ids directly later, so do not change them casually.
- Terms inside a main topic must name only that component. Split explicitly
  named tools, interventions, exposures, populations, contexts, outcomes,
  targets, settings, mechanisms, measurements, and evidence signals when each
  is independently required for relevance.
- Preserve an explicit valid component phrase from the user rather than
  replacing it with a broader inferred umbrella.
- Include at least four focused `terms` and normally six or more
  `matching_terms` when real vocabulary supports it. Include useful in-family
  names, variants, subtypes, abbreviations, acronyms, and surface forms. Do not
  pad lists with background vocabulary.
- `retrieval_terms` must contain at most twelve high-signal, component-pure
  provider terms. `matching_terms` may be broader but must remain within the
  same concept.
- Use only `title`, `abstract`, or `title_or_abstract` for fields. Default
  generated main topics to `title`; use `title_or_abstract` only for an
  explanatory detail that can be absent from a title without weakening topical
  fit. Do not use abstract-only generated main topics. Required setting,
  context, or population components use `title`.
- Do not replace a concrete comparator, replacement target, application, or use
  case with a broad criterion or motivation. Keep a replacement target and an
  explicitly named application/domain as separate component-pure main topics.
- `secondary_topics` must be grouped objects with `main_topic_id`,
  `secondary_topic_id`, `label`, `field`, `terms`, `retrieval_terms`, and
  `matching_terms`.
- Add a secondary group for every main topic when a clean adjacent sibling
  direction exists. A secondary is a neighboring concept, not a parent alias,
  version, stage, variant, example, or internal subtype.
- Each secondary group names exactly one concept; its term lists contain only
  aliases and surface forms of that secondary concept. Parent and secondary
  term groups must be disjoint. Do not create vague related/other buckets or a
  secondary that repeats a parent term.
- Keep different fallback concepts as separate semantic groups.
- Apply the supplied versioned policy guidance exactly. It is the only source
  for configured concept-specific completions, exclusions, fallback groups,
  common surface forms, and anchor precedence.

Discovery and screening rules:
- Keep discovery recall broad. Include reviews, overviews, datasets, methods,
  and empirical studies unless the user explicitly narrows source types.
- Set `candidate_screening.borderline_policy` and `human_review_policy` to
  include. Missing abstracts are included when title or metadata remains
  plausibly relevant. Borderline or tangentially relevant candidates are
  included when they address one meaningful aspect of the topic.
- Exclude only clearly unrelated material or explicit user exclusions.
- `rule_based_screening.include_terms` must contain useful broad topic
  vocabulary; keep exclusion precedence aligned with the requested scope.
- Preserve the providers available in the base template.
- Set `collection.publication_window` to exact inclusive `start` and `end`
  dates in `YYYY-MM-DD` form only when the user states both boundaries;
  otherwise set it to null. Never infer exact dates that the user did not give.
- Add at least three complementary `collection.search_queries` with a concise
  reason for each query.

Bootstrap tagging rules:
- Set `tagging.evidence_policy` explicitly. Use `abstract_or_full_text` unless
  the user requires identity-verified extracted full text for every tag.
- Tagging categories in this first contract are provisional examples only, not
  the final extraction ontology.
- Include at least one provisional tagging category with multiple concrete
  values so the contract is executable.
- Do not create any root focus selector, whole-question category, metadata
  category, or generic study boilerplate.
- Categories and values use lowercase snake_case and must be answerable from an
  individual paper.
- Use `selection: single` only for mutually exclusive values and `multi` when
  values may co-occur.
- Use `applies_when` only for a conditional category whose parent category and
  trigger values are present.
- Keep fallback policy explicit and do not invent catch-all values.

Return only strict JSON matching the topic-contract schema.
