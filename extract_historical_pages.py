
"""Pulse Sjöden Historical Data Engine v0.1.

Extract text from official Svensk Travsport PDFs.
Keep sources.csv and the SAT engine unchanged.
"""

import argparse
import csv
import hashlib
import json
import tempfile

from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


MAX_BYTES = 65_000_000

ALLOWED_HOSTS = {
    "travsport.se",
    "www.travsport.se",
    "media-cdn.travsport.se",
}


def approved_url(url):
    parts = urlsplit(url)

    try:
        port = parts.port
    except ValueError:
        return False

    return (
        parts.scheme == "https"
        and parts.hostname in ALLOWED_HOSTS
        and not parts.username
        and not parts.password
        and port in (None, 443)
        and parts.path.lower().endswith(".pdf")
    )


def find_document(kind, year):
    with open(
        "official_sources_seed.csv",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(
            line for line in file if line.strip()
        )

        matches = []

        for row in reader:
            if (
                row["kind"].strip() == kind
                and int(row["year"]) == year
                and not row["part"].strip()
                and row["url"].strip()
            ):
                matches.append(row["url"].strip())

    if len(matches) != 1:
        raise ValueError(
            f"Expected one document; found {len(matches)}"
        )

    url = matches[0]

    if not approved_url(url):
        raise ValueError("Unapproved document URL")

    return url


def extract_document(kind, year, max_pages=15):
    from pypdf import PdfReader

    if max_pages < 1:
        raise ValueError("max_pages must be positive")

    url = find_document(kind, year)

    output = Path("historical_output")
    output.mkdir(exist_ok=True)

    digest = hashlib.sha256()

    with tempfile.TemporaryFile(mode="w+b") as pdf:
        request = Request(
            url,
            headers={
                "User-Agent": "PulseSjodenHistory/0.1"
            },
        )

        with urlopen(request, timeout=40) as response:
            if not approved_url(response.geturl()):
                raise ValueError("Unapproved redirect")

            size = 0

            while True:
                chunk = response.read(262144)

                if not chunk:
                    break

                size += len(chunk)

                if size > MAX_BYTES:
                    raise ValueError("PDF exceeds 65 MB")

                digest.update(chunk)
                pdf.write(chunk)

        pdf.seek(0)

        if pdf.read(5) != b"%PDF-":
            raise ValueError("Invalid PDF signature")

        pdf.seek(0)

        reader = PdfReader(pdf, strict=False)
        total_pages = len(reader.pages)

        records = []

        for index in range(min(max_pages, total_pages)):
            try:
                page_text = (
                    reader.pages[index].extract_text()
                    or ""
                )

                status = (
                    "text_extracted"
                    if page_text.strip()
                    else "needs_ocr"
                )

            except Exception as error:
                page_text = ""
                status = (
                    "extraction_error:"
                    + type(error).__name__
                )

            records.append({
                "kind": kind,
                "year": year,
                "page": index + 1,
                "source_url": url,
                "sha256": digest.hexdigest(),
                "status": status,
                "text": page_text,
            })

    name = f"{kind}_{year}"

    pages_file = output / f"{name}_pages.jsonl"
    metadata_file = output / f"{name}_metadata.json"

    with pages_file.open(
        "w",
        encoding="utf-8",
    ) as file:
        for record in records:
            file.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                )
                + "\n"
            )

    metadata = {
        "kind": kind,
        "year": year,
        "source_url": url,
        "sha256": digest.hexdigest(),
        "total_pages": total_pages,
        "pages_extracted": len(records),
        "pages_with_text": sum(
            item["status"] == "text_extracted"
            for item in records
        ),
        "pages_needing_review": sum(
            item["status"] != "text_extracted"
            for item in records
        ),
    }

    metadata_file.write_text(
        json.dumps(
            metadata,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            metadata,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--kind",
        choices=[
            "annual_statistics",
            "annual_report",
        ],
        default="annual_statistics",
    )

    parser.add_argument(
        "--year",
        type=int,
        default=2019,
    )

    parser.add_argument(
        "--pages",
        type=int,
        default=15,
    )

    args = parser.parse_args()

    extract_document(
        kind=args.kind,
        year=args.year,
        max_pages=args.pages,
    )
