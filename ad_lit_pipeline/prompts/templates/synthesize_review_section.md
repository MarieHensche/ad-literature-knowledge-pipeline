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
- Treat the review as the configured review type in the overview. Do not call it
  a systematic review unless the packet explicitly says it is systematic and
  provides systematic-review methods.
- For `main_topic_lens` sections, discuss the configured main topic as a
  conceptual lens across the papers; do not simply repeat method summaries.
- For comparative sections, compare patterns across labels, datasets, findings,
  limitations, and study designs instead of restating prior sections.
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
