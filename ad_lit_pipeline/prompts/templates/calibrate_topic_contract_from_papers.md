You are calibrating the tagging ontology of a literature-pipeline topic
contract after candidate papers have been collected and full text has been
extracted.

User research question:
$topic_description

Current topic contract:
$current_contract_json

Selected primary-paper full-text evidence:
$primary_papers_json

Task:
Return JSON with:
- a complete topic contract whose non-tagging sections are preserved and whose
  existing `tagging.categories` are lightly calibrated against the selected
  primary-paper full-text evidence.

Rules:
- Use the current review-derived ontology as the starting point. Do not invent a
  completely new ontology from the primary papers alone.
- Use primary-paper `full_text_evidence` only to check whether categories and
  values are answerable, too broad, too narrow, missing, redundant, or clearly
  mismatched to the real corpus.
- This is a light polish step after review-based ontology generation. Improve
  existing tagging categories and values; do not redesign the ontology around
  the few primary papers.
- Preserve `research_topic`, `topic_structure`, `scope`,
  `rule_based_screening`, `candidate_screening`, `collection`, and
  `tagging.fallback_policy`. This task is only about knowledge tagging
  categories and values.
- Preserve the existing category IDs whenever possible. You may improve
  category descriptions, add/remove/rename values inside existing categories,
  and remove values that the selected full texts show are weak or redundant.
- Do not add a new category unless it is strictly necessary to keep an existing
  `knowledge_goal` root value backed by a sibling facet category. Do not add
  categories for distinctions visible in only one selected paper.
- Remove or replace values that appear contaminated by off-topic review
  evidence or that do not fit the actual research topic.
- The first tagging category must have category_id `knowledge_goal`, required
  true, selection `single`, and applies_when null.
- Treat `knowledge_goal` as the primary research-focus selector over the
  topic's major evidence-derived facets. The id stays `knowledge_goal` for
  pipeline compatibility, but conceptually this is the paper's dominant facet.
- `knowledge_goal` values must be exact `category_id` values of sibling facet
  categories that you also return. Each matching sibling category must contain
  detailed allowed values for how that facet is researched or reported.
- The pipeline will deterministically synchronize `knowledge_goal.values` to
  valid sibling facet category IDs after your response. Do not use
  `knowledge_goal` for paper-by-paper assignment in this step.
- Each matching sibling facet category should usually have `applies_when` null
  so papers can still record secondary information about non-dominant facets.
  Use conditional categories only for narrower follow-up questions that truly
  make sense for a subset of facet values.
- Prefer 3 to 6 `knowledge_goal` values. Do not create more `knowledge_goal`
  values than the selected primary-paper full texts can support.
- `knowledge_goal` values must be topic-facet nouns or noun phrases grounded in
  the evidence, not vague benefit/action or whole-question phrases such as
  `improving_x`, `enhancing_y`, `supporting_z`, `studying_x`, `evaluating_y`,
  `effect_of_x`, `impact_of_x`, `role_of_x`, or `relationship_between_x_y`.
- Keep categories that are useful and answerable across the paper corpus.
- Add a category or value only when the primary full-text evidence shows that it
  would help tag multiple relevant papers.
- Split a value that would absorb most papers; merge values that are synonyms or
  are too hard to distinguish from paper text.
- Prefer topic-specific categories over generic methodology buckets. Do not add
  generic categories such as `study_design`, `study_population`,
  `data_source_type`, `study_type`, or `publication_type`.
- Do not add categories for topical fit, paper selection, review status,
  confidence, extraction basis, paper metadata, authors, journals, or single
  paper titles.
- Use conditional sub-categories with `applies_when` when a question only makes
  sense for a subset of the root `knowledge_goal` values.
- Do not add `unclear`, `mixed_or_unclear`, `not_reported`, `other`,
  `not_applicable`, or `unknown` as values in generated knowledge categories.
- Prefer 6 to 10 compact knowledge categories when the evidence supports them.
- Category IDs and allowed values must use lowercase snake_case.
- Return JSON matching the topic-contract schema. In `tagging.categories`, return
  an array of category objects with `category_id`, `description`, `required`,
  `selection`, `values`, and `applies_when`.
