# Task

Draft one section of a scientific literature review from the provided evidence
packet.

# Rules

- Use only information present in the evidence packet.
- Do not invent papers, methods, results, limitations, or statistics.
- Write concise academic prose in Markdown.
- Use natural Harvard author-year inline citations from `citation_papers`,
  such as `(Smith et al., 2021)`.
- Do not use internal paper-id markers such as `[p1]`.
- Cite factual claims naturally without citation clutter.
- Direct quotations may only come from `quotes` in the section packet.
- Direct quotations must be cited immediately with a Harvard citation.
- Prefer synthesis across papers over listing papers one by one.
- If evidence is thin, say so carefully instead of overclaiming.
- Follow the section packet's `section_type`, `purpose`, and `topic_focus`.
- For `abstract`, write one self-contained paragraph of approximately 150 to
  250 words containing: brief supported context, the review objective and
  scope, the configured review type and evidence base, the most important
  synthesis-level findings, principal supported limitations or gaps, and the
  main conclusion or implication. Do not use citations, quotations, headings,
  bullets, internal paper ids, detailed search strings, or unsupported facts.
  Return empty citation and quotation arrays for this section.
- Treat `chapter_label` as the parent chapter and write only the subsection
  defined by this packet. Do not repeat material assigned to sibling
  subsections in the same chapter.
- For `introduction`, write a conventional scientific literature-review
  introduction that:
  1. establishes the supported broader context and central research problem;
  2. explains why the topic matters using only evidence available in the packet;
  3. states the review objective, scope, and conceptual boundaries;
  4. introduces the configured main topics as organizing concepts; and
  5. previews the review structure and broad evidence landscape.
  Keep detailed search procedures in `review_methodology`, and keep detailed
  findings, comparisons, limitations, and conclusions in their later sections.
  Cite factual background claims, but the review's own objective and structural
  roadmap do not require citations.
- Treat the review as the configured review type in the overview. Do not call it
  a systematic review unless the packet explicitly says it is systematic and
  provides systematic-review methods.
- For `main_topic_lens` sections, discuss the configured main topic as a
  conceptual lens across the papers; do not simply repeat method summaries.
- For comparative sections, compare patterns across labels, datasets, findings,
  limitations, and study designs instead of restating prior sections.
- Within **Methods and Analytical Approaches**, keep method distribution in
  `methodological_landscape`, direct cross-method comparison in
  `comparison_of_approaches`, and finding-level convergence or divergence in
  `evidence_patterns_across_approaches`.
- Within **Data Foundations and Study Designs**, keep data origin in
  `datasets_and_data_sources`, sample or population characteristics in
  `samples_cohorts_and_populations`, and design or validation in
  `study_designs_and_validation_strategies`.
- Within **Limitations and Research Outlook**, keep paper-reported limitations,
  explicit gaps, and explicitly stated future directions separate. Never invent
  a gap or recommendation.
- Do not directly compare or rank performance scores from different papers unless
  the packet shows comparable data, tasks, outcomes, and validation settings.
  Otherwise describe performance patterns qualitatively and contextually.
- Use any `method_hierarchy_hints` to avoid treating broad method families and
  their subtypes as equal, independent categories.
- For `review_methodology`, describe only pipeline-supported review methods and
  counts available in the packet, including databases/providers, search queries,
  inclusion/exclusion criteria, review-paper filtering, label coverage, and
  citation eligibility when present.
- Avoid repeating the same evidence claims across sections; each section should
  serve its stated purpose.
- Return `cited_paper_ids` for every paper cited in `body_markdown`,
  `citation_support`, or `quote_uses`.
- Prioritize citing as many citation-eligible papers in this section as useful.

# Research Topic

$research_topic_json

# Review Overview

$overview_json

# Quality Context

$quality_json

# Section Evidence Packet

$section_json

# Output

Return strict JSON matching the schema. Keep `section_id` identical to the input
section id. `cited_paper_ids`, `citation_support.paper_id`, and
`quote_uses.paper_id` must refer to paper ids present in the section packet.
