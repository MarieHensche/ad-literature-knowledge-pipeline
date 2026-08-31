# Topic-Contract Bootstrap And Refinement Plan

Status: superseded by the implemented workflow

This file is retained so existing links do not become misleading or broken. Its
former implementation instructions have been completed and are no longer an
active plan.

The implemented contract-bootstrap workflow is:

```text
generate_topic_contract
-> fetch_review_overviews
-> prepare_review_full_text
-> refine_topic_contract
```

Generation creates the discovery structure and a structurally valid provisional
tagging section. Refinement receives bounded evidence from readable review full
texts, omits provisional categories from its prompt context, enforces final
tagging quality, and can apply a targeted tagging-only repair before retrying a
full refinement. When no usable review text exists, refinement fails instead of
silently presenting an abstract-derived ontology as review-grounded.

Current topic-structure vocabulary and heuristics come from the versioned
portable policy, not embedded domain examples. Generated and refined contracts
record the selected policy identity.

Use these current sources instead:

- [Technical summary](technical_summary.md)
- [Topic-structure policy](topic_structure_policy.md)
- [Pipeline registry](pipeline_registry.md)
- [Living gap-discovery implementation plan](gap_discovery_implementation_plan.md)

Git history preserves the former detailed implementation checklist if it is
needed for archaeology. Do not use that checklist to infer current behavior.
