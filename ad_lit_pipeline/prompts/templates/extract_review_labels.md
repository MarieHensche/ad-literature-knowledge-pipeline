You extract paper-level labels for literature-review generation.

Research topic:
$research_topic_json

Topic structure:
$topic_structure_json

Review label config:
$review_config_json

Paper:
$paper_json

Task:
Extract review-only labels for this one paper.

Rules:
- Return JSON only.
- Return every configured label under `labels`.
- Follow each label's `description`, `extraction_rule`,
  `max_values_per_paper`, `max_words_per_value`, `max_items_per_paper`,
  `max_words_per_item`, and `missing_value`.
- Use controlled values only when allowed values are provided.
- For controlled_auto labels, return compact lowercase snake_case values.
- The topic structure describes collection concepts. Its term hints may help
  interpret the paper, but do not assume a topic term belongs to a review label
  unless it matches that label's description and the paper evidence supports it.
- Use the section-focused evidence for each label first. The
  `available_section_headings` list may help identify semantically similar
  sections, but do not invent evidence from sections not included in
  `evidence_by_label`.
- For free_text labels, use concise citation-ready text grounded in the evidence.
- For free_text labels with multiple allowed items, separate items with
  semicolons.
- For evidence_quote labels, return exact short direct quotations from the paper
  evidence, including the section and why the quote is useful.
- Do not invent findings, quotes, methods, or limitations.
- Prefer the supplied section-focused evidence over the abstract when possible.
- Keep direct quotations short and scientifically useful.
- Use empty arrays for unsupported controlled or quote labels.
- Use an empty string for unsupported free-text labels.
- Include evidence_sections_used and extraction_notes.
