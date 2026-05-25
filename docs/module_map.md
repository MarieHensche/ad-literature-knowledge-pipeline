# Module Map

The script names remain as compatibility wrappers. Reusable behavior now lives
under `ad_lit_pipeline/`.

| CLI wrapper | Package module |
| --- | --- |
| `scripts/run_pipeline.py` | `ad_lit_pipeline/cli/run_pipeline.py` |
| `scripts/run_collection.py` | `ad_lit_pipeline/cli/run_collection.py` |
| `scripts/normalize_metadata.py` | `ad_lit_pipeline/steps/metadata/normalize.py` |
| `scripts/screen_scope.py` | `ad_lit_pipeline/steps/screening/rule_based_scope.py` |
| `scripts/normalize_tagging_config.py` | `ad_lit_pipeline/steps/tagging/normalize_config.py` |
| `scripts/generate_tagging_rules.py` | `ad_lit_pipeline/steps/tagging/generate_rules.py` |
| `scripts/tag_papers_with_llm.py` | `ad_lit_pipeline/steps/tagging/tag_papers.py` |
| `scripts/audit_extraction.py` | `ad_lit_pipeline/steps/tagging/audit.py` |
| `scripts/export_mantis_ready.py` | `ad_lit_pipeline/steps/export/mantis.py` |
| `scripts/plan_library_search.py` | `ad_lit_pipeline/steps/collection/plan_search.py` |
| `scripts/fetch_openalex_candidates.py` | `ad_lit_pipeline/steps/collection/fetch_candidates.py` and `ad_lit_pipeline/providers/openalex.py` |
| `scripts/deduplicate_candidates.py` | `ad_lit_pipeline/steps/collection/deduplicate.py` |
| `scripts/screen_candidates_with_llm.py` | `ad_lit_pipeline/steps/screening/llm_candidate_screening.py` |
| `scripts/export_screened_candidates_to_csv.py` | `ad_lit_pipeline/steps/collection/export_included.py` |

Topic-specific scope, fallback policy, category values, and enabled providers
live in `configs/topics/early_detection_ad.yaml`.

Prompt text lives in `ad_lit_pipeline/prompts/templates/`.

Run manifests are written to `runs/<run_id>/manifest.json`.
