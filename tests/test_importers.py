from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path


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


def test_import_bibtex_example_to_canonical_csv(tmp_path: Path) -> None:
    output = tmp_path / "papers.csv"

    run_script(
        "scripts/import_bibtex.py",
        "--input",
        "data/raw/example_papers.bib",
        "--output",
        str(output),
    )

    rows = read_csv(output)
    assert len(rows) == 3
    assert rows[0]["paper_id"] == "example_001"
    assert rows[0]["doi"] == "10.1145/3644116.3644192"
    assert rows[0]["authors"] == "Li, Example; Chen, Example"
    assert rows[0]["venue"] == "ACM"
    assert rows[0]["source"] == "bibtex:inproceedings"
    assert rows[0]["notes"] == "bibtex_key=example_001"


def test_import_jsonl_example_to_canonical_csv(tmp_path: Path) -> None:
    output = tmp_path / "papers.csv"

    run_script(
        "scripts/import_json_metadata.py",
        "--input",
        "data/raw/example_papers.jsonl",
        "--output",
        str(output),
    )

    rows = read_csv(output)
    assert len(rows) == 3
    assert rows[0]["paper_id"] == "json_001"
    assert rows[0]["year"] == "2024"
    assert rows[0]["authors"] == "Example Author"
    assert rows[0]["source"] == "json_metadata"
    assert rows[0]["notes"] == "json_row=1"


def test_import_ris_example_to_canonical_csv(tmp_path: Path) -> None:
    output = tmp_path / "papers.csv"

    run_script(
        "scripts/import_ris.py",
        "--input",
        "data/raw/example_papers.ris",
        "--output",
        str(output),
    )

    rows = read_csv(output)
    assert len(rows) == 3
    assert rows[0]["paper_id"] == "10_0000_ris-example1"
    assert rows[0]["doi"] == "10.0000/ris-example1"
    assert rows[0]["authors"] == "Example Author"
    assert rows[0]["venue"] == "Example Conference"
    assert rows[0]["source"] == "ris:CONF"
    assert rows[0]["notes"] == "ris_row=1"
