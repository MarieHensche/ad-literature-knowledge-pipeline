from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_EMAIL = "ad-lit-pipeline@example.invalid"


@dataclass(frozen=True)
class FullTextLocation:
    """Resolved full-text location for a paper."""

    status: str
    source: str = ""
    url: str = ""
    local_path: str = ""
    license: str = ""
    manual_lookup_url: str = ""


def normalize_doi(value: object) -> str:
    doi = str(value or "").strip()
    doi = doi.replace("https://doi.org/", "")
    doi = doi.replace("http://doi.org/", "")
    doi = doi.replace("doi:", "")
    return doi.strip()


def first_value(*values: object) -> str:
    for value in values:
        if value:
            return str(value)
    return ""


def is_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def location_key(location: FullTextLocation) -> tuple[str, str]:
    return (location.url or location.local_path, location.status)


def add_location(
    locations: list[FullTextLocation],
    location: FullTextLocation,
    seen: set[tuple[str, str]],
) -> None:
    if location.status == "not_found":
        return

    key = location_key(location)
    if key[0] and key in seen:
        return
    locations.append(location)
    if key[0]:
        seen.add(key)


def manual_lookup_url(doi: str, title: str) -> str:
    query = doi or title
    if not query:
        return ""
    return "https://scholar.google.com/scholar?q=" + urllib.parse.quote(query)


def location_from_openalex_location(
    location: dict[str, Any],
    source: str,
    fallback_is_oa: bool,
) -> list[FullTextLocation]:
    if not isinstance(location, dict):
        return []

    is_oa = bool(location.get("is_oa") or fallback_is_oa)
    locations: list[FullTextLocation] = []

    pdf = first_value(location.get("pdf_url"), location.get("url_for_pdf"))
    if pdf:
        locations.append(
            FullTextLocation(
                status="open_pdf_found",
                source=source,
                url=pdf,
                license=first_value(location.get("license")),
            )
        )

    landing = first_value(
        location.get("landing_page_url"),
        location.get("url_for_landing_page"),
        location.get("url"),
    )
    if landing and is_oa:
        locations.append(
            FullTextLocation(
                status="open_landing_found",
                source=source,
                url=landing,
                license=first_value(location.get("license")),
            )
        )

    return locations


def provider_locations_from_record(record: dict[str, Any]) -> list[FullTextLocation]:
    open_access = record.get("open_access") or {}
    if not isinstance(open_access, dict):
        open_access = {}

    fallback_is_oa = bool(open_access.get("is_oa"))
    locations: list[FullTextLocation] = []
    seen: set[tuple[str, str]] = set()

    for key in ("best_oa_location", "primary_location"):
        value = record.get(key) or {}
        if isinstance(value, dict):
            for location in location_from_openalex_location(
                value,
                source="provider_metadata",
                fallback_is_oa=fallback_is_oa,
            ):
                add_location(locations, location, seen)

    oa_url = first_value(open_access.get("oa_url"))
    if oa_url:
        status = "open_pdf_found" if ".pdf" in oa_url.lower() else "open_landing_found"
        add_location(
            locations,
            FullTextLocation(
                status=status,
                source="provider_metadata",
                url=oa_url,
            ),
            seen,
        )

    for value in record.get("locations") or []:
        if not isinstance(value, dict):
            continue
        for location in location_from_openalex_location(
            value,
            source="provider_metadata",
            fallback_is_oa=fallback_is_oa,
        ):
            add_location(locations, location, seen)

    return locations


def provider_location_from_record(record: dict[str, Any]) -> FullTextLocation:
    locations = provider_locations_from_record(record)
    return locations[0] if locations else FullTextLocation(status="not_found")


class NetworkFullTextResolver:
    """Resolve open full-text URLs across provider-independent DOI services."""

    def __init__(
        self,
        email: str | None = None,
        core_api_key: str | None = None,
        timeout_seconds: int = 45,
    ) -> None:
        self.email = email or os.getenv("UNPAYWALL_EMAIL") or DEFAULT_EMAIL
        self.core_api_key = core_api_key or os.getenv("CORE_API_KEY", "")
        self.timeout_seconds = timeout_seconds

    def get_json(self, url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        request_headers = dict(headers or {})
        request_headers.setdefault(
            "User-Agent", f"ad-literature-knowledge-pipeline/0.1 ({self.email})"
        )
        request = urllib.request.Request(url, headers=request_headers)
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))

        if not isinstance(data, dict):
            return {}
        return data

    def resolve(self, row: dict[str, str]) -> FullTextLocation:
        for location in self.resolve_all(row):
            return location
        return FullTextLocation(status="not_found")

    def resolve_all(self, row: dict[str, str]) -> list[FullTextLocation]:
        doi = normalize_doi(row.get("doi"))
        title = row.get("title", "")
        locations: list[FullTextLocation] = []
        seen: set[tuple[str, str]] = set()

        local = self.local_path_location(row)
        add_location(locations, local, seen)

        direct = self.direct_url_location(row)
        add_location(locations, direct, seen)

        for lookup in (
            self.lookup_openalex_all,
            self.lookup_unpaywall_all,
            self.lookup_europe_pmc_all,
            self.lookup_core_all,
        ):
            try:
                resolved_locations = lookup(doi, title)
            except Exception:
                resolved_locations = []
            for location in resolved_locations:
                add_location(locations, location, seen)

        locations.append(
            FullTextLocation(
                status="manual_lookup_needed",
                manual_lookup_url=manual_lookup_url(doi, title),
            )
        )
        return locations

    def local_path_location(self, row: dict[str, str]) -> FullTextLocation:
        path_text = first_value(
            row.get("full_text_text_path"),
            row.get("local_text_path"),
            row.get("full_text_path"),
        )
        if not path_text or is_url(path_text):
            return FullTextLocation(status="not_found")

        path = Path(path_text).expanduser()
        if path.exists():
            return FullTextLocation(
                status="local_full_text_found",
                source="input_full_text_path",
                local_path=str(path),
            )
        return FullTextLocation(status="not_found")

    def direct_url_location(self, row: dict[str, str]) -> FullTextLocation:
        url = first_value(
            row.get("full_text_url"),
            row.get("pdf_url"),
            row.get("oa_url"),
            row.get("full_text_path") if is_url(row.get("full_text_path", "")) else "",
        )
        if not url:
            return FullTextLocation(status="not_found")

        status = "open_pdf_found" if ".pdf" in url.lower() else "open_landing_found"
        return FullTextLocation(status=status, source="input_metadata", url=url)

    def lookup_openalex(self, doi: str, title: str) -> FullTextLocation:
        locations = self.lookup_openalex_all(doi, title)
        return locations[0] if locations else FullTextLocation(status="not_found")

    def lookup_openalex_all(self, doi: str, title: str) -> list[FullTextLocation]:
        if not doi:
            return []

        params = urllib.parse.urlencode({"filter": f"doi:{doi}", "per-page": "1"})
        data = self.get_json(f"https://api.openalex.org/works?{params}")
        results = data.get("results") or []
        if not results or not isinstance(results[0], dict):
            return []

        locations = []
        for location in provider_locations_from_record(results[0]):
            locations.append(
                FullTextLocation(
                    status=location.status,
                    source="openalex",
                    url=location.url,
                    license=location.license,
                )
            )
        return locations

    def lookup_unpaywall(self, doi: str, title: str) -> FullTextLocation:
        locations = self.lookup_unpaywall_all(doi, title)
        return locations[0] if locations else FullTextLocation(status="not_found")

    def lookup_unpaywall_all(self, doi: str, title: str) -> list[FullTextLocation]:
        if not doi:
            return []

        doi_path = urllib.parse.quote(doi, safe="")
        email = urllib.parse.quote(self.email)
        data = self.get_json(f"https://api.unpaywall.org/v2/{doi_path}?email={email}")

        locations: list[FullTextLocation] = []
        seen: set[tuple[str, str]] = set()
        candidates = []
        best = data.get("best_oa_location")
        if isinstance(best, dict):
            candidates.append(best)
        for item in data.get("oa_locations") or []:
            if isinstance(item, dict):
                candidates.append(item)
        for item in data.get("oa_locations_embargoed") or []:
            if isinstance(item, dict):
                candidates.append(item)

        for item in candidates:
            license_value = first_value(item.get("license"))
            pdf = first_value(item.get("url_for_pdf"))
            landing = first_value(item.get("url"), item.get("url_for_landing_page"))

            if pdf:
                add_location(
                    locations,
                    FullTextLocation(
                        status="open_pdf_found",
                        source="unpaywall",
                        url=pdf,
                        license=license_value,
                    ),
                    seen,
                )
            if landing and data.get("is_oa"):
                add_location(
                    locations,
                    FullTextLocation(
                        status="open_landing_found",
                        source="unpaywall",
                        url=landing,
                        license=license_value,
                    ),
                    seen,
                )

        return locations

    def lookup_europe_pmc(self, doi: str, title: str) -> FullTextLocation:
        locations = self.lookup_europe_pmc_all(doi, title)
        return locations[0] if locations else FullTextLocation(status="not_found")

    def lookup_europe_pmc_all(self, doi: str, title: str) -> list[FullTextLocation]:
        if not doi:
            return []

        params = urllib.parse.urlencode(
            {"query": f'DOI:"{doi}"', "format": "json", "pageSize": "1"}
        )
        data = self.get_json(
            f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?{params}"
        )
        results = ((data.get("resultList") or {}).get("result")) or []
        if not results or not isinstance(results[0], dict):
            return []

        urls = (((results[0].get("fullTextUrlList") or {}).get("fullTextUrl")) or [])
        locations: list[FullTextLocation] = []
        seen: set[tuple[str, str]] = set()

        for prefer_pdf in (True, False):
            for item in urls:
                if not isinstance(item, dict):
                    continue
                url = first_value(item.get("url"))
                style = str(item.get("documentStyle") or "").lower()
                is_pdf = "pdf" in style or ".pdf" in url.lower()
                if not url or is_pdf != prefer_pdf:
                    continue
                status = "open_pdf_found" if is_pdf else "open_landing_found"
                add_location(
                    locations,
                    FullTextLocation(status=status, source="europe_pmc", url=url),
                    seen,
                )

        return locations

    def lookup_core(self, doi: str, title: str) -> FullTextLocation:
        locations = self.lookup_core_all(doi, title)
        return locations[0] if locations else FullTextLocation(status="not_found")

    def lookup_core_all(self, doi: str, title: str) -> list[FullTextLocation]:
        if not self.core_api_key:
            return []

        query = doi or title
        if not query:
            return []

        params = urllib.parse.urlencode({"q": query, "limit": "5"})
        data = self.get_json(
            f"https://api.core.ac.uk/v3/search/works?{params}",
            headers={"Authorization": f"Bearer {self.core_api_key}"},
        )
        results = data.get("results") or []
        if not results:
            return []

        locations: list[FullTextLocation] = []
        seen: set[tuple[str, str]] = set()

        for item in results:
            if not isinstance(item, dict):
                continue

            pdf = first_value(item.get("downloadUrl"))
            if pdf:
                add_location(
                    locations,
                    FullTextLocation(
                        status="open_pdf_found", source="core", url=pdf
                    ),
                    seen,
                )

            links = item.get("links") or []
            if isinstance(links, list):
                for link in links:
                    if isinstance(link, dict):
                        url = first_value(link.get("url"))
                    else:
                        url = first_value(link)
                    if url and ".pdf" in url.lower():
                        add_location(
                            locations,
                            FullTextLocation(
                                status="open_pdf_found", source="core", url=url
                            ),
                            seen,
                        )

        for item in results:
            if not isinstance(item, dict):
                continue
            landing = first_value(item.get("url"), item.get("publisherUrl"))
            if landing:
                add_location(
                    locations,
                    FullTextLocation(
                        status="open_landing_found", source="core", url=landing
                    ),
                    seen,
                )

        return locations
