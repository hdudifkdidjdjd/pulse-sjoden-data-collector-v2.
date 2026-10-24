"""Discover and verify official PDF document URLs from Svensk Travsport.

The script validates document candidates before they are adopted into the
production source list. It deliberately targets the official index pages rather
than scraping unrelated sites, and it never overwrites the stable sources.csv
file.
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


class LinkCollector(HTMLParser):
    """Collect candidate URLs and their surrounding text labels."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._current_label: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in {"a", "link", "source", "area", "iframe"}:
            return
        attrs = dict(attrs)
        href = attrs.get("href") or attrs.get("src") or attrs.get("data-url")
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
    return " ".join(value.split()).strip()


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


def infer_document_kind(label: str, url: str, default_kind: str) -> str | None:
    normalized = normalize_space(f"{label} {url}").lower()
    if "arsredovisning" in normalized or "redovisning" in normalized or "annual report" in normalized:
        return "annual_report"
    if "arsstatistik" in normalized or "statistik" in normalized or "annual statistics" in normalized:
        return "annual_statistics"
    return default_kind


def infer_year(label: str, url: str, expected_years: Iterable[int]) -> int | None:
    text = normalize_space(f"{label} {url}")
    years = [int(match) for match in re.findall(r"(20\d{2})", text)]
    if not years:
        return None

    valid = [year for year in years if year in expected_years]
    if valid:
        return valid[0]
    return years[0]


def fetch_page(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json;q=0.9,*/*;q=0.8"})
    with urlopen(request, timeout=30) as response:
        body = response.read(5_000_000)
    return body.decode("utf-8", "replace")


def verify_pdf_url(url: str) -> tuple[bool, str]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*;q=0.8"})
    try:
        with urlopen(request, timeout=30) as response:
            content_type = response.headers.get_content_type() if hasattr(response.headers, "get_content_type") else ""
            payload = response.read(4096)
            if payload and payload.startswith(b"%PDF-"):
                return True, "PDF signature verified"
            if content_type == "application/pdf":
                return True, "Content-Type indicates PDF"
            return False, "Not a PDF or verification failed"
    except (HTTPError, URLError, ValueError):
        return False, "Network or HTTP verification failure"


def collect_discoveries() -> list[dict]:
    discovered: list[dict] = []
    seen: set[tuple[str, int, str]] = set()

    for kind, page_url in PAGES.items():
        expected_years = set(YEAR_RANGES[kind])
        for page in [page_url]:
            try:
                text = fetch_page(page)
            except Exception as exc:  # pragma: no cover - network failure is handled at runtime.
                discovered.append({
                    "kind": kind,
                    "year": None,
                    "url": page_url,
                    "status": "network_error",
                    "note": f"Unable to fetch official index page: {exc}",
                })
                continue

            parser = LinkCollector()
            parser.feed(text)
            gathered: list[tuple[str, str]] = []
            for label, href in parser.links:
                if href and href.strip():
                    gathered.append((label, href))
            for embedded in extract_embedded_urls(text):
                gathered.append((embedded, embedded))

            for label, href in gathered:
                candidate_url = canonical_url(href, page)
                if not candidate_url:
                    continue
                split = urlsplit(candidate_url)
                if split.scheme.lower() != "https" or not split.hostname or not split.hostname.endswith("travsport.se"):
                    continue

                doc_kind = infer_document_kind(label, candidate_url, kind)
                if doc_kind != kind:
                    continue

                year = infer_year(label, candidate_url, expected_years)
                if year is None or year not in expected_years:
                    continue

                record_key = (doc_kind, year, candidate_url)
                if record_key in seen:
                    continue
                seen.add(record_key)

                verified, reason = verify_pdf_url(candidate_url)
                status = "verified" if verified else "candidate"
                note = reason if verified else "Found on official index but not yet verified"
                discovered.append({
                    "kind": doc_kind,
                    "year": year,
                    "url": candidate_url,
                    "status": status,
                    "note": note,
                })

    return discovered


def build_expected_rows() -> list[dict]:
    rows = []
    for kind, years in YEAR_RANGES.items():
        for year in years:
            rows.append({"kind": kind, "year": year, "url": "", "status": "missing", "note": "No official PDF link found during discovery"})
    return rows


def write_candidate_csv(rows: list[dict], destination: Path) -> None:
    ordered = []
    found_by_key = {(row["kind"], row["year"]): row for row in rows if row.get("kind") and row.get("year") is not None}

    for kind, years in YEAR_RANGES.items():
        for year in years:
            key = (kind, year)
            if key in found_by_key:
                ordered.append(found_by_key[key])
            else:
                ordered.append({
                    "kind": kind,
                    "year": year,
                    "url": "",
                    "status": "missing",
                    "note": "No official PDF link found during discovery",
                })

    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["kind", "year", "url", "status", "note"])
        writer.writeheader()
        writer.writerows(ordered)


def diagnostics_for(rows: list[dict]) -> dict:
    expected_total = sum(len(years) for years in YEAR_RANGES.values())
    found = [row for row in rows if row.get("url")]
    verified = [row for row in rows if row.get("status") == "verified"]
    broken = [row for row in rows if row.get("status") == "broken"]
    missing = expected_total - len(found)

    summary = {
        "expected_total": expected_total,
        "found_candidates": len(found),
        "verified_documents": len(verified),
        "missing_documents": missing,
        "broken_links": len(broken),
        "notes": [
            "Only official Svensk Travsport document index pages are accepted.",
            "No URL is approved without PDF verification.",
            "The stable sources.csv file is never overwritten by discovery.",
        ],
    }

    for kind, years in YEAR_RANGES.items():
        summary[kind] = {
            "expected": len(years),
            "found": len([row for row in found if row.get("kind") == kind]),
            "verified": len([row for row in verified if row.get("kind") == kind]),
            "missing": len([year for year in years if not any(row.get("kind") == kind and row.get("year") == year and row.get("url") for row in found)]),
        }

    return summary


def main() -> None:
    discovered = collect_discoveries()
    rows = build_expected_rows()
    for new_row in discovered:
        key = (new_row["kind"], new_row["year"])
        for row in rows:
            if (row["kind"], row["year"]) == key:
                row.update({
                    "url": new_row["url"],
                    "status": new_row["status"],
                    "note": new_row["note"],
                })
                break

    candidate_path = Path("sources_candidates.csv")
    write_candidate_csv(rows, candidate_path)

    diagnostics_path = Path("discovery_diagnostics.json")
    diagnostics = diagnostics_for(rows)
    diagnostics_path.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Discovery complete: {len([row for row in rows if row['url']])} candidate URLs, {len([row for row in rows if row['status'] == 'verified'])} verified PDFs")


if __name__ == "__main__":
    main()
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
