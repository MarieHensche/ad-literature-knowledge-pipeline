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
- For disease-specific method/tool topics such as computational biology methods
  for Alzheimer's disease research, choose the disease as the anchor. The
  disease is non-replaceable; method components can have adjacent method
  secondaries.
- Add secondary-topic fallback groups only when they provide clean adjacent or
  alternate sibling directions for one main topic, including the anchor.
- Secondary topics should be adjacent sibling directions, not narrower internal
  subtypes of broad method, tool, model, analysis, evidence-signal,
  intervention, or platform families.
- If a validation issue names a missing secondary topic, create a useful
  controlled adjacent sibling group for that exact main topic. For disease
  parents, adjacent disease/application directions such as Parkinson's disease,
  cancer, or named non-parent diseases may be appropriate when relevant.
- If a validation issue names a missing secondary topic for a computational
  method parent, create an adjacent non-computational method group such as
  `experimental_methods`, `laboratory_methods`, or `clinical_methods`. Do not
  use AI, ML, deep learning, supervised learning, unsupervised learning,
  statistical modeling, network analysis, or systems biology as secondary
  topics for computational methods; those are parent terms.
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
  each resulting main topic its own secondary fallback group.
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
- Terms inside a main topic must include in-family surface forms for that main
  topic: types, variants, subcategories, versions, stages, other names,
  abbreviations, common synonyms, and narrower indicators that still belong to
  the same family. Do not keep these in-family forms as secondary topics.
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
  the parent terms when they are part of the same disease area. For
  Alzheimer's disease, this can include MCI, prodromal disease, preclinical
  disease, dementia, or dementia-related cognitive impairment when relevant.
  Use secondary topics for neighboring disease/application directions, not for
  variants that belong inside the parent disease family.
- For disease or condition main topics, do not put pathology, mechanism,
  biomarker, symptom, or process terms in the topic term lists. For Alzheimer's
  disease, terms such as tau pathology, amyloid plaques, neurodegeneration, or
  memory loss are not disease-family names; keep them for scope, screening, or
  later tagging categories.
- Keep `retrieval_terms` component-pure; do not mix vocabulary from different
  main topics into one retrieval term.
- Secondary topics must be adjacent sibling directions that go in a different
  direction from the parent, not versions, aliases, variants, types,
  subcategories, synonyms, spelling variants, examples, or narrower subtypes.
  For example, `parkinsons_disease` or `cancer` may be adjacent sibling disease
  directions for an `alzheimers_disease` parent, while dementia, cognitive
  decline, MCI, mild cognitive impairment, prodromal disease, and preclinical
  disease belong in the Alzheimer's disease parent terms. Likewise,
  `machine_learning` and `deep_learning` are internal parts of
  `computational_methods` and belong in the parent terms.
- Each secondary group must name exactly one adjacent concept, and its `terms`,
  `retrieval_terms`, and `matching_terms` must be aliases, variants, types,
  abbreviations, or surface forms of that one secondary concept. Do not keep
  vague secondary buckets such as `related_diseases`, `other_diseases`, or
  `dementia_types`. For example, use a `parkinsons_disease` group with terms
  such as Parkinson's disease, Parkinson disease, and PD, and a separate
  `cancer` group with terms such as cancer, neoplasm, and tumor. Do not put
  generic descriptors such as `dementia types`, `neurodegenerative diseases`,
  or `cognitive impairments` in a secondary group's term lists.
- Parent and secondary term groups must be disjoint across `terms`,
  `retrieval_terms`, and `matching_terms`. If a secondary term overlaps the
  parent or is an in-family subtype, move it into the parent terms or remove the
  secondary group.
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
- Include commonly used surface forms explicitly when they matter:
  abbreviations and full forms such as `AI` and `artificial intelligence`,
  spelling or punctuation variants such as `A.I.` when common in the
  literature, and common synonyms. Do not add rare, invented, or merely
  capitalization-only variants.
- Use only `title`, `abstract`, or `title_or_abstract` for fields.
- Use compact lowercase snake_case ids.
- Return JSON matching the topic-structure schema.
