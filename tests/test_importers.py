from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

from ad_lit_pipeline.steps.importers import bibtex, json_metadata, ris


ROOT = Path(__file__).resolve().parents[1]


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def assert_bibtex_example_rows(rows: list[dict[str, str]]) -> None:
    assert len(rows) == 3
    assert rows[0]["paper_id"] == "example_001"
    assert rows[0]["doi"] == "10.1145/3644116.3644192"
    assert rows[0]["authors"] == "Li, Example; Chen, Example"
    assert rows[0]["venue"] == "ACM"
    assert rows[0]["source"] == "bibtex:inproceedings"
    assert rows[0]["notes"] == "bibtex_key=example_001"


def assert_jsonl_example_rows(rows: list[dict[str, str]]) -> None:
    assert len(rows) == 3
    assert rows[0]["paper_id"] == "json_001"
    assert rows[0]["year"] == "2024"
    assert rows[0]["authors"] == "Example Author"
    assert rows[0]["source"] == "json_metadata"
    assert rows[0]["notes"] == "json_row=1"


def assert_ris_example_rows(rows: list[dict[str, str]]) -> None:
    assert len(rows) == 3
    assert rows[0]["paper_id"] == "10_0000_ris-example1"
    assert rows[0]["doi"] == "10.0000/ris-example1"
    assert rows[0]["authors"] == "Example Author"
    assert rows[0]["venue"] == "Example Conference"
    assert rows[0]["source"] == "ris:CONF"
    assert rows[0]["notes"] == "ris_row=1"


def test_import_bibtex_run_example_to_canonical_csv(tmp_path: Path) -> None:
    output = tmp_path / "papers.csv"

    result = bibtex.run(ROOT / "data/raw/example_papers.bib", output)

    assert result.step_name == "import_bibtex"
    assert result.row_counts["papers"] == 3
    assert_bibtex_example_rows(read_csv(output))


def test_import_bibtex_script_wrapper_example_to_canonical_csv(tmp_path: Path) -> None:
    output = tmp_path / "papers.csv"

    run_script(
        "scripts/import_bibtex.py",
        "--input",
        "data/raw/example_papers.bib",
        "--output",
        str(output),
    )

    assert_bibtex_example_rows(read_csv(output))


def test_import_jsonl_run_example_to_canonical_csv(tmp_path: Path) -> None:
    output = tmp_path / "papers.csv"

    result = json_metadata.run(ROOT / "data/raw/example_papers.jsonl", output)

    assert result.step_name == "import_json_metadata"
    assert result.row_counts["papers"] == 3
    assert_jsonl_example_rows(read_csv(output))


def test_import_jsonl_script_wrapper_example_to_canonical_csv(tmp_path: Path) -> None:
    output = tmp_path / "papers.csv"

    run_script(
        "scripts/import_json_metadata.py",
        "--input",
        "data/raw/example_papers.jsonl",
        "--output",
        str(output),
    )

    assert_jsonl_example_rows(read_csv(output))


def test_import_json_container_run_to_canonical_csv(tmp_path: Path) -> None:
    input_path = tmp_path / "papers.json"
    output = tmp_path / "papers.csv"
    input_path.write_text(
        json.dumps(
            {
                "papers": [
                    {
                        "paperId": "JSON Example 1",
                        "title": "Example JSON Metadata Paper",
                        "publicationYear": 2025,
                        "externalIds": {"DOI": "https://doi.org/10.0000/json-example"},
                        "abstract": "A JSON metadata record.",
                        "authors": [{"display_name": "JSON Author"}],
                        "publicationVenue": {"name": "JSON Journal"},
                        "openAccessPdf": {"url": "https://example.com/paper.pdf"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = json_metadata.run(input_path, output)

    rows = read_csv(output)
    assert result.row_counts["papers"] == 1
    assert rows[0]["paper_id"] == "json_example_1"
    assert rows[0]["doi"] == "10.0000/json-example"
    assert rows[0]["authors"] == "JSON Author"
    assert rows[0]["venue"] == "JSON Journal"
    assert rows[0]["url"] == "https://example.com/paper.pdf"


def test_import_ris_run_example_to_canonical_csv(tmp_path: Path) -> None:
    output = tmp_path / "papers.csv"

    result = ris.run(ROOT / "data/raw/example_papers.ris", output)

    assert result.step_name == "import_ris"
    assert result.row_counts["papers"] == 3
    assert_ris_example_rows(read_csv(output))


def test_import_ris_script_wrapper_example_to_canonical_csv(tmp_path: Path) -> None:
    output = tmp_path / "papers.csv"

    run_script(
        "scripts/import_ris.py",
        "--input",
        "data/raw/example_papers.ris",
        "--output",
        str(output),
    )

    assert_ris_example_rows(read_csv(output))
