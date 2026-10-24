import argparse
import csv
import hashlib
import json
from pathlib import Path
import urllib.request

KINDS = {"annual_statistics": set(range(2001, 2020)), "annual_report": set(range(2015, 2026))}
MAX_BYTES = 30_000_000

def load_sources(path):
    with open(path, newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["kind", "year", "url"]:
            raise ValueError("Expected columns: kind,year,url")
        rows = list(reader)
    seen = set()
    for row in rows:
        kind, year, url = row["kind"], int(row["year"]), row["url"].strip()
        if kind not in KINDS or year not in KINDS[kind]:
            raise ValueError(f"Unexpected source: {kind}/{year}")
        if (kind, year) in seen:
            raise ValueError(f"Duplicate source: {kind}/{year}")
        seen.add((kind, year))
        if url and not url.startswith("https://"):
            raise ValueError(f"HTTPS required: {kind}/{year}")
    expected = {(kind, year) for kind, years in KINDS.items() for year in years}
    if seen != expected:
        raise ValueError(f"Missing entries: {sorted(expected - seen)}")
    return rows

def download(rows, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    records = []
    for row in rows:
        kind, year, url = row["kind"], int(row["year"]), row["url"].strip()
        item = {"kind": kind, "year": year, "source_url": url, "status": "missing_url"}
        if url:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "PulseSjodenCollector/0.1"})
                with urllib.request.urlopen(req, timeout=30) as response:
                    data = response.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise ValueError("File exceeds 30 MB")
                if not data.startswith(b"%PDF-"):
                    raise ValueError("Response is not a PDF")
                path = output / f"{kind}_{year}.pdf"
                path.write_bytes(data)
                item.update(status="downloaded", path=str(path), bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
            except Exception as exc:
                item.update(status="error", error=str(exc))
        records.append(item)
    (output / "manifest.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    return records

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["validate", "download"])
    parser.add_argument("--sources", default="sources.csv")
    parser.add_argument("--output", default="data/raw")
    args = parser.parse_args()
    rows = load_sources(args.sources)
    print(f"Validated {len(rows)} sources; {sum(bool(r['url'].strip()) for r in rows)} URLs supplied")
    if args.command == "download":
        records = download(rows, args.output)
        print(f"Downloaded {sum(r['status'] == 'downloaded' for r in records)} PDFs; see manifest.json")

if __name__ == "__main__":
    main()
