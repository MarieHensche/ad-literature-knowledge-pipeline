You are extracting first-class knowledge findings from one scientific source.

Research topic:
$research_topic_json

Known topic IDs:
$topic_ids_json

Source:
$source_json

Evidence excerpts:
$evidence_excerpts_json

Return atomic findings only.

Rules:
- Each finding must express one claim about one outcome in one context using one method.
- Use only the evidence excerpts provided here.
- Every finding must cite at least one provided evidence_excerpt_id.
- Use topic_ids only from the known topic IDs list.
- Preserve positive, negative, mixed, null, and inconclusive findings.
- Do not invent results, methods, populations, datasets, or outcomes.
- If the evidence does not support any clear finding, return an empty findings list.
- Use extraction_confidence for confidence that the extraction is correct.
- Use evidence_strength for the strength of scientific support.
- Keep claim_text concise and source-grounded.
