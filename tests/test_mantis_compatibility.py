from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from ad_lit_pipeline.core.registry import (
    COLLECTION_PIPELINE,
    MAIN_PIPELINE,
    MANTIS_DELIVERY_PIPELINE,
    PIPELINE_SPECS,
    STEP_CATALOG,
)
from ad_lit_pipeline.steps.export import mantis


MANIFEST_PATH = (
    Path(__file__).parent / "fixtures" / "compatibility" / "v1" / "manifest.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_step_1_7_registry_compatibility_matrix_is_frozen() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    registry = manifest["registry"]

    assert len(STEP_CATALOG) == registry["steps"]
    assert len(PIPELINE_SPECS) == registry["pipelines"]
    assert list(MAIN_PIPELINE) == registry["default_main"]
    assert list(MANTIS_DELIVERY_PIPELINE) == registry["optional_mantis_delivery"]
    assert "export_mantis_views" not in MAIN_PIPELINE
    assert "publish_mantis_views" not in MAIN_PIPELINE
    assert "publish_mantis_views" not in COLLECTION_PIPELINE


def test_legacy_mantis_export_retains_its_frozen_parsed_contract(
    tmp_path: Path,
) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    legacy = manifest["legacy_export"]
    output = tmp_path / "legacy_mantis.csv"

    result = mantis.run(Path(legacy["input"]), output)

    assert result.row_counts["mantis_rows"] == legacy["rows"]
    with output.open(encoding="utf-8", newline="") as handle:
        actual_rows = list(csv.DictReader(handle))
    with Path(legacy["expected"]).open(encoding="utf-8", newline="") as handle:
        expected_rows = list(csv.DictReader(handle))
    assert actual_rows == expected_rows
    assert _sha256(Path(legacy["expected"])) == legacy["sha256"]
