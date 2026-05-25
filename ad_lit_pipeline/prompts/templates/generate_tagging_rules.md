You are preparing fixed tagging rules for a scientific literature knowledge-tagging pipeline.

The rules will be generated once, frozen, and then applied consistently to every paper.

Research topic:
$research_topic_json

Categories and allowed values:
$categories_json

Topic fallback policy:
$fallback_policy_json

Per-category fallback recommendations:
$fallback_recommendations_json

For each category, decide:
- selection: "single" if exactly one value should usually be chosen, or "multi" if more than one value may be valid.
- required: true if the category should be filled for every included paper, otherwise false.
- fallback_value: one allowed value from that category to use when the paper is unclear or not enough information is available.

Rules:
- Return exactly one rule per category.
- Use only the provided category_id values.
- Use the exact fallback_value shown in the per-category fallback recommendations when one is provided.
- fallback_value must be one of the allowed values for that exact category.
- Never use "unclear" as fallback_value unless "unclear" is explicitly listed as an allowed value for that category.
- If the topic fallback policy prefers unclear and "unclear" is allowed, prefer it as the fallback_value.
- If the topic fallback policy prefers mixed_or_unclear and "mixed_or_unclear" is allowed while "unclear" is not allowed, use "mixed_or_unclear" as the fallback_value.
- If "not_reported" is allowed, use it when missing information is the likely issue.
- Follow category-specific fallback values in the topic fallback policy.
- If a category is marked required in the input config, keep it required.
- Do not invent new categories or values.
