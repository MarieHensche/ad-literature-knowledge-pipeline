from __future__ import annotations


MAIN_PIPELINE = [
    "normalize_metadata",
    "screen_scope",
    "normalize_tagging_config",
    "generate_tagging_rules",
    "tag_papers",
    "audit_extraction",
    "export_mantis",
]

COLLECTION_PIPELINE = [
    "plan_search",
    "fetch_candidates",
    "deduplicate_candidates",
    "screen_candidates",
    "export_included_candidates",
]

COLLECTION_WITH_CONTRACT_PIPELINE = [
    "generate_topic_contract",
    *COLLECTION_PIPELINE,
]
