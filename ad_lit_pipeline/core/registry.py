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

MAIN_PIPELINE_WITH_CALIBRATION = [
    "normalize_metadata",
    "screen_scope",
    "prepare_full_text",
    "calibrate_topic_contract",
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
    "screen_title_relevance",
    "verify_full_text_availability",
    "backfill_candidates",
    "export_included_candidates",
]

COLLECTION_CALIBRATION_PIPELINE = [
    "select_calibration_papers",
    "prepare_calibration_full_text",
    "calibrate_topic_contract",
]

CONTRACT_BOOTSTRAP_PIPELINE = [
    "generate_topic_contract",
    "fetch_review_overviews",
    "prepare_review_full_text",
    "refine_topic_contract",
]

COLLECTION_WITH_CONTRACT_PIPELINE = [
    *CONTRACT_BOOTSTRAP_PIPELINE,
    *COLLECTION_PIPELINE,
]
