# Task

Draft one section of a scientific literature review from the provided evidence
packet.

# Rules

- Use only information present in the evidence packet.
- Do not invent papers, methods, results, limitations, or statistics.
- Write concise academic prose in Markdown.
- Use paper ids in inline citation markers like `[p1]` or `[p1; p2]`.
- Direct quotations may only come from `quotes` in the section packet.
- Prefer synthesis across papers over listing papers one by one.
- If evidence is thin, say so carefully instead of overclaiming.

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
section id. `citation_support.paper_id` and `quote_uses.paper_id` must refer to
paper ids present in the section packet.
