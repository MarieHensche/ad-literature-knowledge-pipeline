from __future__ import annotations


MAIN_PIPELINE = [
    "normalize_metadata",
    "screen_scope",
    "prepare_full_text",
    "normalize_tagging_config",
    "generate_tagging_rules",
    "tag_papers",
    "audit_extraction",
    "export_mantis",
]

COLLECTION_PIPELINE = [
    "plan_search",
    "collect_targeted_candidates",
]

LEGACY_COLLECTION_PIPELINE = [
    "plan_search",
    "fetch_candidates",
    "deduplicate_candidates",
    "screen_candidates",
    "export_included_candidates",
]

CONTRACT_BOOTSTRAP_PIPELINE = [
    "generate_topic_contract",
    "fetch_review_overviews",
    "refine_topic_contract",
]

COLLECTION_WITH_CONTRACT_PIPELINE = [
    *CONTRACT_BOOTSTRAP_PIPELINE,
    *COLLECTION_PIPELINE,
]

LEGACY_COLLECTION_WITH_CONTRACT_PIPELINE = [
    *CONTRACT_BOOTSTRAP_PIPELINE,
    *LEGACY_COLLECTION_PIPELINE,
]
