from __future__ import annotations

import csv
from pathlib import Path


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    """Read a CSV file into dictionaries."""
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_csv_with_fieldnames(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Read a CSV file and return its header plus row dictionaries."""
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_csv_rows(
    path: Path,
    rows: list[dict[str, str]],
    fieldnames: list[str],
) -> None:
    """Write dictionaries to a CSV file using an explicit header."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

