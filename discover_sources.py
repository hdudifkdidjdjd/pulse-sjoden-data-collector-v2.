"""Discover and verify official PDF document links from Svensk Travsport.

This version intentionally keeps the stable collector core untouched and focuses
on source discovery, verification, and candidate reporting.
"""
from __future__ import annotations

import csv
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

PAGES = {
    "annual_statistics": "https://www.travsport.se/sport/statistik/arsstatistik",
    "annual_report": "https://www.travsport.se/svensk-travsport/organisation/arsredovisning",
}

YEAR_RANGES = {
    "annual_statistics": range(2001, 2020),
    "annual_report": range(2015, 2026),
}

USER_AGENT = "PulseSjodenCollector/0.4 (+official-document-discovery)"
KIND_KEYWORDS = {
    "annual_statistics": [
        "arsstatistik",
        "aarsstatistik",
        "annual statistics",
        "statistik",
    ],
    "annual_report": [
        "arsredovisning",
        "aarsredovisning",
        "annual report",
        "redovisning",
    ],
}


class LinkCollector(HTMLParser):
    """Collect href values and their surrounding descriptive text."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._current_label: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in {"a", "link", "source", "area", "iframe"}:
            return
        values = dict(attrs)
        href = values.get("href") or values.get("src") or values.get("data-url")
        if href:
            self._current_href = href
            self._current_label = []

    def handle_data(self, data):
        if self._current_href is not None:
            text = data.strip()
            if text:
                self._current_label.append(text)

    def handle_endtag(self, tag):
        if tag not in {"a", "link", "source", "area", "iframe"}:
            return
        if self._current_href is not None:
            label = " ".join(" ".join(self._current_label).split())
            self.links.append((label, self._current_href))
            self._current_href = None
            self._current_label = []


def normalize_space(value: str) -> str:
    return " ".join(str(value).split()).strip()


def canonical_url(raw_url: str, base_url: str) -> str:
    url = urljoin(base_url, raw_url.strip())
    if not url:
        return ""
    split = urlsplit(url)
    return split._replace(fragment="").geturl()


def extract_embedded_urls(text: str) -> set[str]:
    urls = set()
    for candidate in re.findall(r"https?://[^\s\"'<>]+", text, flags=re.I):
        if candidate.lower().endswith(".pdf") or "pdf" in candidate.lower():
            urls.add(candidate)
    return urls


def infer_document_kind(label: str, url: str) -> str | None:
    combined = normalize_space(f"{label} {url}").lower()
    for kind, keywords in KIND_KEYWORDS.items():
        if any(keyword in combined for keyword in keywords):
            return kind
    return None


def infer_year(label: str, url: str, expected_years: Iterable[int]) -> int | None:
    text = normalize_space(f"{label} {url}")
    years = [int(match) for match in re.findall(r"(20\d{2})", text)]
    if not years:
        return None
    valid = [year for year in years if year in expected_years]
    if valid:
        return valid[0]
    return Years of the year, used only for close matches


# Compatibility wrapper: keep a clear, explicit year selection for candidate matching.
def extract_years(value: str) -> list[int]:
    return [int(match) for match in re.findall(r"(20\d{2})", value)]


def infer_year(label: str, url: str, expected_years: Iterable[int]) -> int | None:
    candidates = extract_years(normalize_space(f"{label} {url}"))
    valid = [year for year in candidates if year in set(expected_years)]
    if valid:
        return valid[0]
    return candidates[0] if candidates else None


def fetch_page(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        },
    )
    with urlopen(request, timeout=30) as response:
        body = response.read(5_000_000)
    return body.decode("utf-8", "replace")


def pdf_text_sample(payload: bytes) -> str:
    sample = payload[:200_000]
    try:
        return sample.decode("latin-1", "ignore")
    except Exception:
        return ""


def verify_pdf_bytes(payload: bytes, expected_kind: str, expected_year: int) -> tuple[bool, str]:
    if len(payload) < 5 or not payload.startswith(b"%PDF-"):
        return False, "Response does not start with the PDF header signature"

    text = pdf_text_sample(payload).lower()
    year_text = str(expected_year)
    kind_keywords = KIND_KEYWORDS[expected_kind]
    kind_present = any(keyword in text for keyword in kind_keywords)
    year_present = year_text in text

    if not year_present:
        return False, f"PDF content does not include the expected year {expected_year}"
    if not kind_present:
        return False, f"PDF content does not include the expected kind markers for {expected_kind}"

    return True, f"PDF body includes matching document year {expected_year} and expected {expected_kind} markers"


def verify_pdf_url(url: str, expected_kind: str, expected_year: int) -> tuple[bool, str]:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/pdf,*/*;q=0.8",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = response.read(200_000)
    except (HTTPError, URLError, ValueError) as exc:
        return False, f"HTTP or network verification failed: {exc}"

    if not payload or not payload.startswith(b"%PDF-"):
        return False, "Downloaded payload is not a valid PDF file"

    if response.headers.get_content_type() == "application/pdf":
        content_type_ok = True
    else:
        content_type_ok = "pdf" in response.headers.get_content_type().lower() if hasattr(response.headers, "get_content_type") else False

    # The PDF must also be checked for document content markers, not only the MIME type.
    bytes_ok, bytes_msg = verify_pdf_bytes(payload, expected_kind, expected_year)
    if not bytes_ok:
        return False, bytes_msg
    if content_type_ok or bytes_ok:
        return True, "Verified by PDF bytes and year/kind markers"
    return False, "Downloaded object was not verifiable as a valid PDF document"


def expected_pairs() -> list[tuple[str, int]]:
    pairs: list[tuple[str, int]] = []
    for kind, years in YEAR_RANGES.items():
        for year in years:
            pairs.append((kind, year))
    return pairs


def row_key(row: dict) -> tuple[str, int]:
    return row["kind"], int(row["year"])


def build_expected_rows() -> list[dict]:
    rows = []
    for kind, years in YEAR_RANGES.items():
        for year in years:
            rows.append({
                "kind": kind,
                "year": year,
                "url": "",
                "status": "missing",
                "note": "No official PDF link found during discovery",
            })
    return rows


def load_existing_sources(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    normalized = []
    for row in rows:
        normalized.append({
            "kind": row.get("kind", "").strip(),
            "year": row.get("year", "").strip(),
            "url": row.get("url", "").strip(),
        })
    return normalized


def merge_candidate_rows(existing_rows: list[dict], discovered_rows: list[dict]) -> list[dict]:
    by_key: dict[tuple[str, int], dict] = {}

    for row in existing_rows:
        key = (row["kind"], int(row["year"]))
        if row.get("url"):
            by_key[key] = {
                "kind": row["kind"],
                "year": int(row["year"]),
                "url": row["url"],
                "status": "existing",
                "note": "Retained from sources.csv; not overwritten by discovery",
            }

    for row in discovered_rows:
        key = (row["kind"], int(row["year"]))
        if key in by_key:
            continue
        by_key[key] = row

    ordered: list[dict] = []
    for kind, year in expected_pairs():
        if (kind, year) in by_key:
            ordered.append(by_key[(kind, year)])
        else:
            ordered.append({
                "kind": kind,
                "year": year,
                "url": "",
                "status": "missing",
                "note": "No official PDF link found during discovery",
            })
    return ordered


def write_candidate_csv(rows: list[dict], destination: Path) -> None:
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["kind", "year", "url", "status", "note"])
        writer.writeheader()
        writer.writerows(rows)


def diagnostics_for(rows: list[dict]) -> dict:
    fuzzy = [row for row in rows if row.get("status") in {"candidate", "verified", "ambiguous"}]
    verified = [row for row in rows if row.get("status") == "verified"]
    missing = [row for row in rows if row.get("status") == "missing"]
    ambiguous = [row for row in rows if row.get("status") == "ambiguous"]
    broken = [row for row in rows if row.get("status") == "broken"]

    summary = {
        "expected_total": 30,
        "found_candidates": len(fuzzy),
        "verified_documents": len(verified),
        "missing_documents": len(missing),
        "ambiguous_documents": len(ambiguous),
        "broken_links": len(broken),
        "notes": [
            "Only official documents from Svensk Travsport are accepted.",
            "The stable sources.csv is never overwritten by discovery.",
            "Every accepted PDF URL is validated for content markers and expected year/kind information.",
        ],
    }
    summary["annual_statistics"] = {
        "expected": len(YEAR_RANGES["annual_statistics"]),
        "found": len([row for row in fuzzy if row.get("kind") == "annual_statistics"]),
        "verified": len([row for row in verified if row.get("kind") == "annual_statistics"]),
        "missing": len([row for row in missing if row.get("kind") == "annual_statistics"]),
        "ambiguous": len([row for row in ambiguous if row.get("kind") == "annual_statistics"]),
    }
    summary["annual_report"] = {
        "expected": len(YEAR_RANGES["annual_report"]),
        "found": len([row for row in fuzzy if row.get("kind") == "annual_report"]),
        "verified": len([row for row in verified if row.get("kind") == "annual_report"]),
        "missing": len([row for row in missing if row.get("kind") == "annual_report"]),
        "ambiguous": len([row for row in ambiguous if row.get("kind") == "annual_report"]),
    }
    return summary


def collect_discoveries() -> list[dict]:
    discovered: list[dict] = []
    seen: set[tuple[str, int, str]] = set()

    for kind, page_url in PAGES.items():
        expected_years = set(YEAR_RANGES[kind])
        try:
            html = fetch_page(page_url)
        except Exception as exc:
            discovered.append({
                "kind": kind,
                "year": None,
                "url": page_url,
                "status": "network_error",
                "note": f"Unable to fetch official index page: {exc}",
            })
            continue

        parser = LinkCollector()
        parser.feed(html)
        gathered: list[tuple[str, str]] = []
        for label, href in parser.links:
            if href and href.strip():
                gathered.append((label, href))
        for embedded in extract_embedded_urls(html):
            gathered.append((embedded, embedded))

        by_year: dict[int, list[str]] = {}
        for label, href in gathered:
            candidate_url = canonical_url(href, page_url)
            if not candidate_url:
                continue
            split = urlsplit(candidate_url)
            if split.scheme.lower() != "https" or not split.hostname or not split.hostname.endswith("travsport.se"):
                continue
            inferred_kind = infer_document_kind(label, candidate_url)
            if inferred_kind is None:
                continue
            if inferred_kind != kind:
                continue
            year = infer_year(label, candidate_url, expected_years)
            if year is None or year not in expected_years:
                continue
            by_year.setdefault(year, []).append(candidate_url)

        for year, urls in sorted(by_year.items()):
            unique_urls = list(dict.fromkeys(urls))
            for url in unique_urls:
                record_key = (kind, year, url)
                if record_key in seen:
                    continue
                seen.add(record_key)
                verified, reason = verify_pdf_url(url, kind, year)
                status = "verified" if verified else "candidate"
                if not verified:
                    reason = f"Candidate detected but not verified: {reason}"
                discovered.append({
                    "kind": kind,
                    "year": year,
                    "url": url,
                    "status": status,
                    "note": reason,
                })
            if len(unique_urls) > 1:
                for url in unique_urls:
                    for row in discovered:
                        if row["kind"] == kind and row["year"] == year and row["url"] == url:
                            row["status"] = "ambiguous"
                            row["note"] = "Multiple candidate URLs found for the same year; no silent override performed. Candidates: " + " | ".join(unique_urls)
                            break

    return discovered


def main() -> None:
    discovered = collect_discoveries()
    existing = load_existing_sources(Path("sources.csv"))
    merged = merge_candidate_rows(existing, discovered)

    candidate_path = Path("sources_candidates.csv")
    write_candidate_csv(merged, candidate_path)

    diagnostics_path = Path("discovery_diagnostics.json")
    diagnostics_data = diagnostics_for(merged)
    diagnostics_path.write_text(json.dumps(diagnostics_data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Discovery complete: {len([row for row in merged if row['url']])} URLs reported; {len([row for row in merged if row['status'] == 'verified'])} verified PDFs; {len([row for row in merged if row['status'] == 'ambiguous'])} ambiguous entries")


if __name__ == "__main__":
    main()
