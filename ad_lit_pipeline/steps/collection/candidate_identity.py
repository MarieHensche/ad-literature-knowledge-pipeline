from __future__ import annotations

import re
from typing import Any


def normalize_doi(value: Any) -> str:
    doi = str(value or "").strip().lower()
    doi = doi.replace("https://doi.org/", "")
    doi = doi.replace("http://doi.org/", "")
    doi = doi.replace("doi:", "")
    return doi.strip()


def normalize_title(value: Any) -> str:
    title = str(value or "").lower()
    title = re.sub(r"[^a-z0-9]+", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def dedupe_key(row: dict[str, Any]) -> str:
    doi = normalize_doi(row.get("doi"))
    if doi:
        return f"doi:{doi}"

    title = normalize_title(row.get("title"))
    year = str(row.get("year") or "").strip()

    if title and year:
        return f"title_year:{title}:{year}"

    if title:
        return f"title:{title}"

    provider = row.get("provider") or "unknown"
    provider_id = row.get("provider_id") or ""
    return f"provider_id:{provider}:{provider_id}"
