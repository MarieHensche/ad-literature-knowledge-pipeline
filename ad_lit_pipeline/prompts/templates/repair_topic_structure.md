You are repairing only the topic structure of a literature-pipeline topic
contract.

User research question:
$topic_description

Current topic structure:
$topic_structure_json

Validation issues:
$validation_issues_json

Versioned topic-structure policy guidance:
$topic_policy_guidance

Task:
Return a corrected `topic_structure` object only. Do not return or change any
other contract section.

Rules:
- Repair every listed validation issue with the smallest coherent structural
  change.
- Keep one necessary conceptual area per main topic. Split merged concepts and
  keep every term list component-pure.
- Choose the non-replaceable title-screening concept as the anchor and set its
  field to `title`. For source/tool/intervention questions, anchor on the source
  when the destination without that source would be off-topic.
- Use `title` for required relevance components. Use `title_or_abstract` only
  for explanatory details, and never use abstract-only generated main topics.
- Preserve explicit user component wording. Do not replace a concrete target,
  comparator, application, or use case with a broad criterion or motivation.
- Add focused in-family names, variants, subtypes, abbreviations, acronyms, and
  surface forms when needed. Keep retrieval terms high-signal,
  component-pure, and limited to twelve.
- Secondary topics are clean adjacent sibling directions, not aliases,
  versions, stages, variants, examples, or internal subtypes of their parent.
  Each group names one concept and uses only that concept's surface forms.
- Parent and secondary term sets must be disjoint. Remove duplicate, vague,
  generic, or mixed secondary groups.
- Apply the supplied versioned policy guidance exactly for concept-specific
  completion, exclusion, fallback, surface-form, and anchor rules.
- Use only compact lowercase snake_case ids and supported topic fields.
- Return JSON matching the topic-structure schema.
