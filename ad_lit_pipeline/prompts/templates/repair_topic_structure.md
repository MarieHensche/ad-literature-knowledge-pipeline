You are repairing only the `topic_structure` of a generated literature-pipeline
topic contract.

User research question:
$topic_description

Current topic structure candidate:
$topic_structure_json

Structured validation issues:
$validation_issues_json

Task:
Return only a complete repaired `topic_structure` JSON object.

Rules:
- Do not return a full topic contract.
- Preserve valid main topics whenever possible.
- Keep `anchor_topic_id` as one of the main topic ids.
- If the validation issues say the source/tool/intervention/material should be
  the anchor, set `anchor_topic_id` to that main topic. For questions like
  "Could X be used to..." or "Use of X in/for...", X is usually the
  non-replaceable anchor, not the application, outcome, or replacement goal.
- Do not define secondary replacements for the anchor.
- Add secondary-topic fallback groups only when they provide clean adjacent or
  alternate wording for one non-anchor main topic.
- Broad method, tool, model, analysis, evidence-signal, intervention, or
  platform families may have multiple secondary-topic groups when there are
  genuinely distinct adjacent expansions.
- If a validation issue names a missing non-anchor secondary topic, create a
  useful controlled fallback group for that exact main topic only when such
  adjacent wording is available.
- If the missing secondary topic is an application/domain topic, add adjacent
  application/domain wording rather than criterion wording. For building
  materials, use groups such as `construction_products`, `building_products`,
  `structural_materials`, or `insulation_materials`; do not leave the topic
  without a fallback after removing invalid green, eco, renewable, or
  sustainability wording.
- If a validation issue says a broad family has too few secondary topics, add
  another distinct secondary group for that same main topic only when it is a
  real fallback, not padding.
- Secondary groups should provide adjacent or alternate wording that can replace
  one parent main topic during recall-oriented discovery.
- Do not make secondary groups simple restatements of parent terms.
- If a secondary group needs one bridge term from the parent, include it only
  when there are also genuinely new fallback terms.
- Keep each main topic to exactly one conceptual area.
- If the validation issues say explicit paired concepts are buried under an
  umbrella topic, split those named concepts into separate main topics and give
  each non-anchor topic its own secondary fallback group.
- If the validation issues say a broad criterion or motivation topic is being
  used instead of a concrete comparator/application, replace that broad main
  topic with a concrete replacement, comparator, material, application, or use
  case main topic from the user question.
- If the validation issues say a replacement target is not a main topic, add a
  main topic whose id/label represents that concrete target or replacement
  relation. For example, use `concrete_replacement` or `concrete`; do not leave
  `concrete` only inside terms for a broader `building_materials` topic.
- If validation issues say a replacement/comparator topic has criterion,
  application, or foreign-component terms, remove those terms. Keep only
  target-specific substitution wording, such as concrete replacement, concrete
  alternative, cement substitute, or the domain-equivalent target terms. Remove
  broad material-family terms such as bare biomaterials, biodegradable
  materials, or bio-based alternatives unless tied to the replacement target.
- If the validation issues say a replacement application/domain is not a main
  topic, add a separate main topic for that application/domain. For example,
  keep `building_materials` separate from `concrete_replacement` when both are
  explicit in the user topic.
- If the user explicitly names a valid component phrase, preserve that wording
  in the main topic id/label and move inferred nearby wording into secondary
  groups. For example, use `building_materials` as the main topic when the user
  says building materials; use `construction_products` or `building_products`
  as secondary groups.
- If validation issues say an application/domain topic has generic terms, use
  concrete domain synonyms or product/application names instead of broad words
  such as innovative, technology, advanced, or materials science.
- If validation issues say an application/domain topic or secondary group has
  process, property, or evaluation wording, replace it with wording that names
  nearby use areas, product families, settings, or domains. Avoid terms like
  `structural integrity`, `construction innovations`, `building techniques`,
  `effective products`, or `responsible practices` unless that property/process
  is the actual research object.
- If validation issues say an application/domain secondary group has criterion
  terms, replace the whole secondary group with adjacent application/domain
  wording. For building-material topics, prefer groups such as
  `construction_products`, `building_products`, `structural_materials`, or
  `insulation_materials`; do not use `eco_friendly_materials`,
  `green_alternatives`, `renewable_materials`, or sustainability criteria.
- If validation issues say a main topic has too few terms, add focused
  synonyms, variants, abbreviations, named subtypes, or concrete indicators for
  that same component when the vocabulary supports it. Do not pad with broad
  background words.
- Keep `retrieval_terms` component-pure; do not mix vocabulary from different
  main topics into one retrieval term.
- Avoid broad standalone terms such as `education`, `learning environment`,
  `educational settings`, `performance metrics`, `technology`, `tools`,
  `educational technology`, `digital technology`, `outcomes`, or `students`.
- Set the anchor main topic's `field` to `title`.
- Default every generated main topic to `title`. Use `title_or_abstract` only
  for detail or explanatory dimensions that can be absent from the title
  without weakening collection relevance, such as mechanisms, validation,
  workflows, measurement details, implementation details, or explanatory
  processes.
- Do not use `abstract` for generated main topics. If a concept may appear only
  outside titles and is still required for relevance, keep it as a `title`
  main topic with richer terms rather than weakening the field.
- Setting, context, or population components should use `title` whenever they
  are required for relevance.
- Include domain-specific named variants, abbreviations, subtypes, tools, and
  concrete indicators for each component.
- Use only `title`, `abstract`, or `title_or_abstract` for fields.
- Use compact lowercase snake_case ids.
- Return JSON matching the topic-structure schema.
