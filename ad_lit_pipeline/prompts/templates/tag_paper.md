You are tagging one scientific paper for a knowledge-map pipeline.

Research topic:
$research_topic_json

Topic scope:
$scope_text

Paper:
$paper_json

Full-text use:
- If `full_text_available_for_tagging` is "yes", base the tags primarily on
  `full_text_evidence`, using title and abstract for context.
- If full-text evidence is absent, tag from the available title and abstract,
  and use `full_text_needed` for `review_status` when that value is configured
  and the missing full text prevents confident tagging.
- Pay special attention to methods, study design, data, analysis, results, and
  conclusions in the full-text evidence. These fields will also support later
  research-method tagging.

Allowed categories and values:
$categories_json

Fixed tagging rules:
$rules_json

Task:
Assign the best-fitting knowledge tags for this paper.

Rules:
- Use only the allowed category IDs.
- Use only allowed values listed for each category.
- Return every category as an array of selected values.
- For single-selection categories, return exactly one value in the array.
- For multi-selection categories, return one or more values if relevant.
- If the paper does not provide enough information, use the category fallback value from the fixed rules.
- Do not invent new values.
- If `main_topic_category` offers `core_topic`, `adjacent_but_relevant`, and
  `out_of_scope`, use it as a strict topical-fit judgment: choose `core_topic`
  only for papers directly about the research topic, preserving the roles in the
  topic. If the topic is about a phenomenon/intervention/tool used in a specific
  context or population and its impact on an outcome, a core paper must study
  that phenomenon in that context and connect it to that outcome.
- Identify the primary subject anchor before assigning `main_topic_category`. In
  topics phrased like "use of X in Y and its impact on Z", X-in-Y is the primary
  anchor; Z is an outcome dimension. A paper should not be core merely because it
  focuses on Z.
- Do not choose `core_topic` when a key topic term appears only as the paper's
  research method, prediction model, measurement tool, or evaluation technique
  rather than as the studied phenomenon/intervention/exposure.
- If the paper uses the topic technology to predict, classify, measure, or
  evaluate the topic outcome, but does not study use of that technology in the
  requested context, tag it as `adjacent_but_relevant` or `out_of_scope`, not
  `core_topic`.
- If the requested context or population is replaced by a broader/different one,
  tag it as `adjacent_but_relevant` unless the contract explicitly makes that
  context core.
- Do not broaden named settings, institutional levels, populations, or domains.
  For example, if the topic says school education, university, college, or
  general higher education is context-shifted and should not be core unless the
  contract explicitly includes it as core.
- Use `adjacent_but_relevant` for papers that meaningfully support the topic but
  miss or substitute one core dimension, and `out_of_scope` for weak or
  mismatched papers.
- main_knowledge_claim should be one concise sentence describing what the paper contributes to the research topic.
$review_status_instruction
