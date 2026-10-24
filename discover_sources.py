
"""Svensk Travsport source discovery v0.5.

Review-first discovery. Never modifies sources.csv.

Produces:
- sources_candidates.csv
- discovery_document_details.csv
- discovery_diagnostics.json

The three documents for annual statistics 2010 are
treated as a single year only after individual verification.
"""

from __future__ import annotations

import csv
import html
import json
import re
import tempfile

from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import Request, urlopen


VERSION = "0.5"

PAGES = {
    "annual_statistics": (
        "https://www.travsport.se/sport/statistik/arsstatistik"
    ),
    "annual_report": (
        "https://www.travsport.se/"
        "svensk-travsport/organisation/arsredovisning"
    ),
}

RANGES = {
    "annual_statistics": range(2001, 2020),
    "annual_report": range(2015, 2026),
}

HOSTS = {
    "travsport.se",
    "www.travsport.se",
    "media-cdn.travsport.se",
}

YEAR = re.compile(r"(?<!\d)(20\d{2})(?!\d)")

STATS = re.compile(
    r"(?:års|aars|ars)[\s_-]*statistik|"
    r"annual[\s_-]*statistics",
    re.I,
)

REPORT = re.compile(
    r"(?:års|aars|ars)[\s_-]*redov(?:isning|ning)|"
    r"annual[\s_-]*report",
    re.I,
)

PDF_URL = re.compile(
    r"""(?:https?://|/)[^\s"'<>\\]+?\.pdf(?:\?[^\s"'<>\\]*)?""",
    re.I,
)

FIELDS = (
    "kind",
    "year",
    "url",
    "status",
    "note",
)

PARTS_2010 = {
    "aktiva",
    "hastar",
    "tavlingar",
}

MAX_PDF_BYTES = 65_000_000
CHUNK_SIZE = 256 * 1024

USER_AGENT = (
    "PulseSjodenCollector/0.5 "
    "(public document verification)"
)


class LinkParser(HTMLParser):

    def __init__(self):
        super().__init__()
        self.links = []
        self.active = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        for attr in (
            "href",
            "src",
            "data-url",
            "data-href",
        ):
            val = attrs.get(attr)

            if val and ".pdf" in val.lower():
                self.links.append(("", val))

        if tag == "a":
            self.active = (
                attrs.get("href", ""),
                [],
            )

    def handle_data(self, data):
        if self.active is not None:
            self.active[1].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.active is not None:
            url, label = self.active

            self.links.append(
                (
                    " ".join("".join(label).split()),
                    url,
                )
            )

            self.active = None


def safe_url(raw, base):
    raw = (
        html.unescape(raw.strip())
        .replace("\\/", "/")
        .replace("\\u002F", "/")
    )

    url = urljoin(base, raw).split("#", 1)[0]
    parts = urlsplit(url)

    try:
        port = parts.port
    except ValueError:
        return None

    if parts.scheme != "https":
        return None

    if (parts.hostname or "").lower() not in HOSTS:
        return None

    if parts.username or parts.password:
        return None

    if port not in (None, 443):
        return None

    if not unquote(parts.path).lower().endswith(".pdf"):
        return None

    return url


def classify(label, url):
    content = unquote(
        label + " " + urlsplit(url).path
    )

    years = set(
        map(int, YEAR.findall(content))
    )

    stats = bool(STATS.search(content))
    report = bool(REPORT.search(content))

    if len(years) != 1:
        return None

    if stats == report:
        return None

    kind = (
        "annual_statistics"
        if stats
        else "annual_report"
    )

    year = next(iter(years))

    if year not in RANGES[kind]:
        return None

    return kind, year


def candidates_from_html(source, base):
    parser = LinkParser()
    parser.feed(source)

    decoded = (
        html.unescape(source)
        .replace("\\/", "/")
        .replace("\\u002F", "/")
    )

    links = parser.links + [
        ("", match.group(0))
        for match in PDF_URL.finditer(decoded)
    ]

    result = defaultdict(set)

    for label, raw in links:
        url = safe_url(raw, base)

        if url:
            key = classify(label, url)

            if key:
                result[key].add(url)

    return result


def read_seed(path):
    """Read the official seed CSV safely."""

    slots = defaultdict(dict)

    if not Path(path).exists():
        return slots

    with open(
        path,
        newline="",
        encoding="utf-8-sig",
    ) as handle:

        reader = csv.DictReader(
            line for line in handle
            if line.strip()
        )

        required = {
            "kind",
            "year",
            "part",
            "url",
        }

        if (
            not reader.fieldnames
            or not required.issubset(reader.fieldnames)
        ):
            raise ValueError(
                "Seed CSV requires kind,year,part,url columns"
            )

        for n, row in enumerate(reader, 2):
            kind = (
                row.get("kind") or ""
            ).strip()

            try:
                year = int(
                    (row.get("year") or "").strip()
                )
            except ValueError as exc:
                raise ValueError(
                    f"Seed row {n}: invalid year"
                ) from exc

            part = (
                row.get("part") or ""
            ).strip().lower()

            url = (
                row.get("url") or ""
            ).strip()

            if (
                kind not in RANGES
                or year not in RANGES[kind]
            ):
                raise ValueError(
                    f"Seed row {n}: invalid kind/year"
                )

            if part and (
                kind,
                year,
            ) != (
                "annual_statistics",
                2010,
            ):
                raise ValueError(
                    f"Seed row {n}: unexpected part"
                )

            if (
                kind,
                year,
            ) == (
                "annual_statistics",
                2010,
            ):
                if part and part not in PARTS_2010:
                    raise ValueError(
                        f"Seed row {n}: unknown part"
                    )

            elif part:
                raise ValueError(
                    f"Seed row {n}: part not permitted"
                )

            if part in slots[(kind, year)]:
                raise ValueError(
                    f"Seed row {n}: duplicate document/part"
                )

            if url and not safe_url(
                url,
                PAGES[kind],
            ):
                raise ValueError(
                    f"Seed row {n}: invalid official PDF URL"
                )

            slots[(kind, year)][part] = url

    return slots


def read_original(path):
    """Read the stable sources without changing them."""

    with open(
        path,
        newline="",
        encoding="utf-8-sig",
    ) as handle:

        reader = csv.DictReader(handle)

        if reader.fieldnames != [
            "kind",
            "year",
            "url",
        ]:
            raise ValueError(
                "sources.csv must have columns kind,year,url"
            )

        rows = list(reader)

    expected = {
        (kind, year)
        for kind, years in RANGES.items()
        for year in years
    }

    found = {
        (
            row["kind"],
            int(row["year"]),
        )
        for row in rows
    }

    if (
        found != expected
        or len(rows) != len(expected)
    ):
        raise ValueError(
            "sources.csv must contain exactly "
            "30 unique expected slots"
        )

    return rows


def fetch_index(url, max_bytes=5_000_000):
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
        },
    )

    with urlopen(req, timeout=25) as response:
        data = response.read(max_bytes + 1)

    if len(data) > max_bytes:
        raise ValueError(
            "index_exceeds_limit"
        )

    return data.decode(
        "utf-8",
        "replace",
    )


def inspect_pdf_pages(
    reader,
    kind,
    year,
    max_pages=24,
):
    """Inspect up to 24 selected PDF pages."""

    count = len(reader.pages)

    indices = list(
        range(min(16, count))
    )

    if count > 16:
        indices += list(
            range(
                max(16, count - 8),
                count,
            )
        )

    indices = list(
        dict.fromkeys(indices)
    )[:max_pages]

    marker = (
        STATS
        if kind == "annual_statistics"
        else REPORT
    )

    page_errors = 0
    saw_text = False

    for idx in indices:
        try:
            text = (
                reader.pages[idx].extract_text()
                or ""
            )
        except Exception:
            page_errors += 1
            continue

        if text.strip():
            saw_text = True

        years = set(
            map(int, YEAR.findall(text))
        )

        if (
            year in years
            and marker.search(text)
        ):
            return (
                "document_verified",
                "Year and document type matched "
                f"together on page {idx + 1}/{count}",
            )

    if not saw_text:
        return (
            "pdf_verified",
            "PDF readable; text unavailable on "
            f"{len(indices)} sampled pages "
            f"(errors={page_errors})",
        )

    return (
        "pdf_verified",
        "PDF readable; matching year/type "
        "not established in "
        f"{len(indices)} sampled pages "
        f"(errors={page_errors})",
    )


def verify_pdf(
    url,
    kind,
    year,
    *,
    max_bytes=MAX_PDF_BYTES,
):
    """Download, validate, and inspect an official PDF."""

    if not safe_url(
        url,
        PAGES[kind],
    ):
        return (
            "invalid",
            "url_not_allowed",
        )

    try:
        from pypdf import PdfReader
    except ImportError:
        return (
            "invalid",
            "dependency_missing:pypdf",
        )

    try:
        req = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/pdf",
            },
        )

        with tempfile.TemporaryFile(
            mode="w+b"
        ) as temp:

            count = 0

            with urlopen(
                req,
                timeout=30,
            ) as response:

                final_url = response.geturl()

                if not safe_url(
                    final_url,
                    PAGES[kind],
                ):
                    return (
                        "invalid",
                        "redirect_to_unapproved_url",
                    )

                while True:
                    piece = response.read(
                        CHUNK_SIZE
                    )

                    if not piece:
                        break

                    count += len(piece)

                    if count > max_bytes:
                        return (
                            "invalid",
                            "pdf_exceeds_limit:"
                            f"{max_bytes}_bytes",
                        )

                    temp.write(piece)

            temp.seek(0)

            if temp.read(5) != b"%PDF-":
                return (
                    "invalid",
                    "missing_pdf_signature",
                )

            temp.seek(0)

            try:
                reader = PdfReader(
                    temp,
                    strict=False,
                )

                if len(reader.pages) == 0:
                    return (
                        "invalid",
                        "zero_pages",
                    )

                return inspect_pdf_pages(
                    reader,
                    kind,
                    year,
                )

            except Exception as exc:
                return (
                    "invalid",
                    "pdf_parse_error:"
                    f"{type(exc).__name__}",
                )

    except (
        HTTPError,
        URLError,
        TimeoutError,
        OSError,
        ValueError,
    ) as exc:
        return (
            "invalid",
            "fetch_error:"
            f"{type(exc).__name__}:"
            f"{str(exc)[:110]}",
        )


def build_report(
    existing_rows,
    discovered,
    verification,
):
    """Compatibility with v0.4 unit tests."""

    output = []

    for row in existing_rows:
        kind = row["kind"]
        year = int(row["year"])

        previous = row["url"].strip()

        urls = set(
            discovered.get(
                (kind, year),
                set(),
            )
        )

        if previous:
            urls.add(previous)

        if len(urls) > 1:
            output.append(
                dict(
                    kind=kind,
                    year=year,
                    url=previous,
                    status="ambiguous",
                    note=(
                        "Multiple URLs: "
                        + " | ".join(sorted(urls))
                    ),
                )
            )

        elif len(urls) == 1:
            url = next(iter(urls))

            status, note = verification.get(
                url,
                (
                    "unverified",
                    "Not checked",
                ),
            )

            if previous:
                note = (
                    "Previously registered; "
                    + note
                )

            output.append(
                dict(
                    kind=kind,
                    year=year,
                    url=url,
                    status=status,
                    note=note,
                )
            )

        else:
            output.append(
                dict(
                    kind=kind,
                    year=year,
                    url="",
                    status="missing",
                    note="No official URL discovered",
                )
            )

    return output


def summarize_2010(parts):
    """Require all three verified statistics parts."""

    named = {
        p["part"]: p
        for p in parts
        if p["part"] in PARTS_2010
    }

    if (
        set(named) != PARTS_2010
        or len(parts) != 3
    ):
        return (
            "ambiguous",
            "2010 requires exactly "
            "aktiva, hastar, tavlingar",
        )

    statuses = [
        named[k]["status"]
        for k in sorted(PARTS_2010)
    ]

    if all(
        s == "document_verified"
        for s in statuses
    ):
        return (
            "document_verified",
            "All three 2010 parts individually "
            "document-verified",
        )

    if any(
        s == "invalid"
        for s in statuses
    ):
        return (
            "invalid",
            "At least one 2010 part invalid: "
            + ",".join(statuses),
        )

    if all(
        s in (
            "document_verified",
            "pdf_verified",
        )
        for s in statuses
    ):
        return (
            "pdf_verified",
            "All three 2010 PDFs valid; "
            "text verification incomplete",
        )

    return (
        "unverified",
        "2010 parts still require review: "
        + ",".join(statuses),
    )


def build_inventory(
    original,
    seed,
    discovered,
    checks,
):
    rows = []
    details = []

    for item in original:
        kind = item["kind"]
        year = int(item["year"])

        key = (kind, year)
        existing = item["url"].strip()

        seeded_parts = seed.get(
            key,
            {},
        )

        if (
            key == (
                "annual_statistics",
                2010,
            )
            and PARTS_2010.issubset(
                seeded_parts
            )
        ):
            all_parts = []

            for part in sorted(PARTS_2010):
                url = seeded_parts[part]

                status, note = checks.get(
                    (
                        kind,
                        year,
                        url,
                    ),
                    (
                        "unverified",
                        "Not checked",
                    ),
                )

                record = dict(
                    kind=kind,
                    year=year,
                    part=part,
                    url=url,
                    status=status,
                    note=note,
                )

                all_parts.append(record)
                details.append(record)

            other_urls = (
                set(
                    discovered.get(
                        key,
                        set(),
                    )
                )
                - {
                    p["url"]
                    for p in all_parts
                }
            )

            status, note = summarize_2010(
                all_parts
            )

            if existing or other_urls:
                status = "ambiguous"
                note = (
                    "Additional 2010 PDF candidates "
                    "need manual review"
                )

            rows.append(
                dict(
                    kind=kind,
                    year=year,
                    url=" | ".join(
                        p["url"]
                        for p in all_parts
                    ),
                    status=status,
                    note=note,
                )
            )

            continue

        urls = (
            set(
                discovered.get(
                    key,
                    set(),
                )
            )
            | {
                u
                for u in seeded_parts.values()
                if u
            }
        )

        if existing:
            urls.add(existing)

        if not urls:
            rows.append(
                dict(
                    kind=kind,
                    year=year,
                    url="",
                    status="missing",
                    note="No official URL discovered",
                )
            )
            continue

        for url in sorted(urls):
            status, note = checks.get(
                (
                    kind,
                    year,
                    url,
                ),
                (
                    "unverified",
                    "Not checked",
                ),
            )

            details.append(
                dict(
                    kind=kind,
                    year=year,
                    part="",
                    url=url,
                    status=status,
                    note=note,
                )
            )

        if len(urls) != 1:
            rows.append(
                dict(
                    kind=kind,
                    year=year,
                    url=existing or "",
                    status="ambiguous",
                    note=(
                        "Multiple competing PDFs: "
                        + " | ".join(sorted(urls))
                    ),
                )
            )

        else:
            url = next(iter(urls))

            status, note = checks.get(
                (
                    kind,
                    year,
                    url,
                ),
                (
                    "unverified",
                    "Not checked",
                ),
            )

            rows.append(
                dict(
                    kind=kind,
                    year=year,
                    url=url,
                    status=status,
                    note=note,
                )
            )

    return rows, details


def main():
    original = read_original(
        "sources.csv"
    )

    seed = read_seed(
        "official_sources_seed.csv"
    )

    discovered = defaultdict(set)
    errors = []

    for kind, page in PAGES.items():
        try:
            found = candidates_from_html(
                fetch_index(page),
                page,
            )

            for key, urls in found.items():
                if key[0] == kind:
                    discovered[key].update(urls)

        except (
            HTTPError,
            URLError,
            TimeoutError,
            ValueError,
            OSError,
        ) as exc:
            errors.append(
                {
                    "page": page,
                    "error": (
                        f"{type(exc).__name__}: {exc}"
                    ),
                }
            )

    checks = {}

    for entry in original:
        kind = entry["kind"]
        year = int(entry["year"])

        key = (
            kind,
            year,
        )

        urls = (
            set(
                discovered.get(
                    key,
                    set(),
                )
            )
            | {
                u
                for u in seed.get(
                    key,
                    {},
                ).values()
                if u
            }
        )

        if entry["url"].strip():
            urls.add(
                entry["url"].strip()
            )

        for url in sorted(urls):
            checks[
                (
                    kind,
                    year,
                    url,
                )
            ] = verify_pdf(
                url,
                kind,
                year,
            )

    rows, details = build_inventory(
        original,
        seed,
        discovered,
        checks,
    )

    with open(
        "sources_candidates.csv",
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=FIELDS,
        )

        writer.writeheader()
        writer.writerows(rows)

    with open(
        "discovery_document_details.csv",
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "kind",
                "year",
                "part",
                "url",
                "status",
                "note",
            ),
        )

        writer.writeheader()
        writer.writerows(details)

    categories = (
        "document_verified",
        "pdf_verified",
        "unverified",
        "ambiguous",
        "invalid",
        "missing",
    )

    counts = {
        status: sum(
            row["status"] == status
            for row in rows
        )
        for status in categories
    }

    result = {
        "version": VERSION,
        "total_expected": len(rows),
        "counts": counts,
        "errors": errors,
        "documents": details,
        "notes": [
            "sources.csv is read-only",
            "2010 requires all three parts",
            "PDF signature alone does not "
            "prove document identity",
            "Failed downloads are not "
            "silently approved",
        ],
    }

    Path(
        "discovery_diagnostics.json"
    ).write_text(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            counts,
            ensure_ascii=False,
        )
    )

    if errors:
        print(
            "Index errors:",
            errors,
        )


if __name__ == "__main__":
    main()
