
"""Discover official Svensk Travsport PDF candidates.

Version 0.3 — experimental source discovery.
Never modifies sources.csv automatically.
"""

import csv
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, unquote
from urllib.request import Request, urlopen

PAGES = {
    "annual_statistics": "https://www.travsport.se/sport/statistik/arsstatistik",
    "annual_report": "https://www.travsport.se/svensk-travsport/organisation/arsredovisning",
}

RANGES = {
    "annual_statistics": (2001, 2019),
    "annual_report": (2015, 2025),
}

HOSTS = {
    "travsport.se",
    "www.travsport.se",
    "media-cdn.travsport.se",
}

YEAR = re.compile(r"(?<!\d)(20\d{2})(?!\d)")

STATS = re.compile(
    r"(?:års|aars|ars)[-_ ]?statistik", re.I
)

REPORT = re.compile(
    r"(?:års|aars|ars)[-_ ]?redovisning|annual[-_ ]?report",
    re.I,
)


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = None
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self.active = {
                "href": dict(attrs).get("href", ""),
                "label": [],
            }

    def handle_data(self, data):
        if self.active is not None:
            self.active["label"].append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.active is not None:
            self.links.append((
                " ".join("".join(self.active["label"]).split()),
                self.active["href"],
            ))
            self.active = None


def classify(label, href, page_kind):
    url = urljoin(PAGES[page_kind], href)
    parsed = urlsplit(url)

    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").lower() not in HOSTS
    ):
        return None

    path = unquote(parsed.path).lower()

    if not path.endswith(".pdf"):
        return None

    combined = unquote(label + " " + path)
    years = set(int(y) for y in YEAR.findall(combined))

    if len(years) != 1:
        return None

    year = years.pop()

    is_stats = bool(STATS.search(combined))
    is_report = bool(REPORT.search(combined))

    if is_stats == is_report:
        return None

    kind = (
        "annual_statistics"
        if is_stats
        else "annual_report"
    )

    low, high = RANGES[kind]

    if not low <= year <= high:
        return None

    return kind, year, url


def discover():
    found = {}

    for kind, page in PAGES.items():
        request = Request(
            page,
            headers={
                "User-Agent": (
                    "PulseSjodenCollector/0.3 "
                    "(public-document-index)"
                )
            },
        )

        with urlopen(request, timeout=30) as response:
            html = response.read(5_000_000).decode(
                "utf-8", "replace"
            )

        parser = Links()
        parser.feed(html)

        print(
            f"{kind}: scanned {len(parser.links)} "
            f"anchor links from {page}"
        )

        for label, href in parser.links:
            match = classify(label, href, kind)

            if match:
                doc_kind, year, url = match

                found.setdefault(
                    (doc_kind, year), set()
                ).add(url)

    return found


def main():
    candidates = discover()

    with open(
        "sources.csv",
        newline="",
        encoding="utf-8",
    ) as source:
        rows = list(csv.DictReader(source))

    output = Path("sources_candidates.csv")
    counts = {}

    with output.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as dest:

        writer = csv.DictWriter(
            dest,
            fieldnames=[
                "kind",
                "year",
                "url",
                "status",
                "note",
            ],
        )

        writer.writeheader()

        for row in rows:
            key = row["kind"], int(row["year"])
            matches = sorted(candidates.get(key, set()))
            existing = row["url"].strip()

            if existing:
                status = "existing"
                note = (
                    "Previously registered; "
                    "not independently verified"
                )
                url = existing

            elif len(matches) == 1:
                status = "candidate"
                note = (
                    "Official index candidate; "
                    "verify PDF content"
                )
                url = matches[0]

            elif len(matches) > 1:
                status = "ambiguous"
                note = (
                    "Multiple candidate URLs: "
                    + " | ".join(matches)
                )
                url = ""

            else:
                status = "not_found"
                note = "No unambiguous PDF anchor found"
                url = ""

            writer.writerow({
                "kind": key[0],
                "year": key[1],
                "url": url,
                "status": status,
                "note": note,
            })

            counts[status] = counts.get(status, 0) + 1

    print(
        f"Wrote {output}: {counts}. "
        "sources.csv unchanged."
    )


if __name__ == "__main__":
    main()
