# Task

Edit the drafted literature-review sections for rigor, consistency, and
readability without adding new evidence.

# Rules

- Use only information present in the evidence map, paper metadata, and draft
  sections.
- Do not add new papers, claims, methods, results, limitations, search details,
  citations, or quotations.
- Preserve every input `section_id`; return one edited section for each draft
  section.
- Keep `cited_paper_ids`, `citation_support.paper_id`, and `quote_uses.paper_id`
  limited to paper ids present in the corresponding evidence section.
- Use the Harvard citation strings implied by the structured paper metadata.
  Do not invent or alter author names.
- Do not use internal paper-id markers such as `[p1]`.
- Remove repeated sentences and merge overlapping claims across sections.
- Strengthen critical comparison where the evidence supports it, especially
  across methods, datasets, validation patterns, limitations, and gaps.
- Do not directly compare or rank performance scores across papers unless the
  evidence shows comparable data, tasks, outcomes, and validation settings.
- State that review-type papers identified by available metadata were excluded;
  do not claim that all included papers were verified original studies unless
  the evidence explicitly proves that.
- Preserve the narrative-review framing unless the overview explicitly says a
  different review type.
- Keep prose concise and scientific.

# Research Topic

$research_topic_json

# Review Overview

$overview_json

# Quality Context

$quality_json

# Structured Paper Metadata

$papers_json

# Evidence Section Packets

$evidence_sections_json

# Draft Sections

$draft_sections_json

# Output

Return strict JSON with a `sections` array. Each edited section must match the
same section schema used by section synthesis.
