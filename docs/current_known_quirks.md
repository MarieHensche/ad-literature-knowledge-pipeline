# Refactor Status And Remaining Quirks

These behaviors were identified before the refactor and are either fixed or
still intentionally documented.

- Fixed: `scripts/screen_scope.py` used to write a narrow CSV and drop optional
  metadata columns such as `authors`, `venue`, `url`, `source`, and
  `full_text_path`. Scope screening now preserves input columns and appends
  scope fields.
- Fixed: `scripts/plan_library_search.py` could recommend providers other than
  OpenAlex while the fetch step could only execute OpenAlex plans. The default
  topic contract enables only OpenAlex, and fetch dispatch rejects unsupported
  providers before network calls.
- Remaining: If LLM paper tagging produces no included rows, `export_mantis_ready.py`
  later fails because it requires at least one extraction row.
- Remaining: `schemas/early_detection_knowledge_schema.yaml` is not yet
  generated from the topic contract, so it can still drift from
  `configs/topics/early_detection_ad.yaml`.
