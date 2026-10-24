"""Review-first official Svensk Travsport PDF discovery, v0.4.

Never changes sources.csv. A PDF is 'pdf_verified' only if its magic bytes match;
'document_verified' requires text extraction and matching year/type markers.
"""
from __future__ import annotations
import csv
import html
import json
import re
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, unquote
from urllib.request import Request, urlopen

PAGES = {
    'annual_statistics': 'https://www.travsport.se/sport/statistik/arsstatistik',
    'annual_report': 'https://www.travsport.se/svensk-travsport/organisation/arsredovisning',
}
RANGES = {'annual_statistics': range(2001, 2020), 'annual_report': range(2015, 2026)}
HOSTS = {'travsport.se', 'www.travsport.se', 'media-cdn.travsport.se'}
YEAR = re.compile(r'(?<!\d)(20\d{2})(?!\d)')
STATS = re.compile(r'(?:års|aars|ars)[\s_-]*statistik|annual[\s_-]*statistics', re.I)
REPORT = re.compile(r'(?:års|aars|ars)[\s_-]*redov(?:isning|ning)|annual[\s_-]*report', re.I)
PDF_URL = re.compile(r'(?:https?://|/)[^\s"\'<>\\]+?\.pdf(?:\?[^\s"\'<>\\]*)?', re.I)
FIELDS = ['kind', 'year', 'url', 'status', 'note']
USER_AGENT = 'PulseSjodenCollector/0.4 (official-public-document-review)'


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.active = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for attr in ('href', 'src', 'data-url', 'data-href'):
            val = attrs.get(attr)
            if val and '.pdf' in val.lower():
                self.links.append(('', val))
        if tag == 'a':
            self.active = (attrs.get('href', ''), [])

    def handle_data(self, data):
        if self.active is not None:
            self.active[1].append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.active is not None:
            url, label = self.active
            self.links.append((' '.join(''.join(label).split()), url))
            self.active = None


def safe_url(raw, base):
    raw = html.unescape(raw).replace('\\/', '/').replace('\\u002F', '/')
    url = urljoin(base, raw).split('#', 1)[0]
    parts = urlsplit(url)
    if parts.scheme != 'https' or (parts.hostname or '').lower() not in HOSTS:
        return None
    if parts.username or parts.password or parts.port not in (None, 443):
        return None
    if not unquote(parts.path).lower().endswith('.pdf'):
        return None
    return url


def classify(label, url):
    content = unquote(label + ' ' + urlsplit(url).path)
    years = set(map(int, YEAR.findall(content)))
    stats, report = bool(STATS.search(content)), bool(REPORT.search(content))
    if len(years) != 1 or stats == report:
        return None
    kind = 'annual_statistics' if stats else 'annual_report'
    year = next(iter(years))
    return (kind, year) if year in RANGES[kind] else None


def candidates_from_html(source, base):
    parser = LinkParser()
    parser.feed(source)
    decoded = html.unescape(source).replace('\\/', '/').replace('\\u002F', '/')
    links = parser.links + [('', match.group(0)) for match in PDF_URL.finditer(decoded)]
    result = defaultdict(set)
    for label, raw in links:
        url = safe_url(raw, base)
        if url:
            key = classify(label, url)
            if key:
                result[key].add(url)
    return result


def request_bytes(url, limit=12_000_000):
    req = Request(url, headers={'User-Agent': USER_AGENT})
    with urlopen(req, timeout=25) as response:
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError('Download exceeds safety limit')
        return data


def pdf_text(data):
    try:
        from pypdf import PdfReader
        from io import BytesIO
        reader = PdfReader(BytesIO(data), strict=False)
        return ' '.join((page.extract_text() or '') for page in reader.pages[:5])
    except Exception:
        return ''


def verify_pdf(url, kind, year):
    try:
        data = request_bytes(url)
        if not data.startswith(b'%PDF-'):
            return 'invalid', 'Missing PDF signature'
        text = pdf_text(data)
        if not text.strip():
            return 'pdf_verified', 'Valid PDF signature; text unavailable for document verification'
        years = set(map(int, YEAR.findall(text)))
        marker = STATS if kind == 'annual_statistics' else REPORT
        if year in years and marker.search(text):
            return 'document_verified', 'PDF text confirms document type and year'
        return 'pdf_verified', 'Valid PDF; document type/year not confirmed in first five pages'
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        return 'invalid', f'Fetch/verification failed: {type(exc).__name__}'


def build_report(existing_rows, discovered, verification):
    output = []
    for row in existing_rows:
        kind, year = row['kind'], int(row['year'])
        key = (kind, year)
        previous = row['url'].strip()
        urls = set(discovered.get(key, set()))
        if previous:
            urls.add(previous)
        if len(urls) > 1:
            output.append(dict(kind=kind, year=year, url=previous, status='ambiguous', note='Multiple URLs: ' + ' | '.join(sorted(urls))))
        elif len(urls) == 1:
            url = next(iter(urls))
            status, note = verification.get(url, ('unverified', 'Not checked'))
            if previous:
                note = 'Previously registered; ' + note
            output.append(dict(kind=kind, year=year, url=url, status=status, note=note))
        else:
            output.append(dict(kind=kind, year=year, url='', status='missing', note='No official URL discovered'))
    return output


def main():
    with open('sources.csv', newline='', encoding='utf-8') as handle:
        original = list(csv.DictReader(handle))
    expected = {(kind, year) for kind, years in RANGES.items() for year in years}
    if {(r['kind'], int(r['year'])) for r in original} != expected or len(original) != len(expected):
        raise ValueError('sources.csv must have exactly the 30 expected kind/year rows')
    discovered = defaultdict(set)
    errors = []
    seed_path = Path("official_sources_seed.csv")
    if seed_path.exists():
        with seed_path.open(
            newline="", encoding="utf-8"
        ) as seed_file:
            for row in csv.DictReader(seed_file):
                kind = row["kind"].strip()
                year = int(row["year"])
                url = row["url"].strip()

                if (
                    kind in RANGES
                    and year in RANGES[kind]
                    and url
                ):
                    checked_url = safe_url(url, PAGES[kind])
                    if checked_url:
                        discovered[(kind, year)].add(checked_url)

    for kind, page in PAGES.items():
        try:
            content = request_bytes(page, 5_000_000).decode('utf-8', 'replace')
            matches = candidates_from_html(content, page)
            for key, urls in matches.items():
                if key[0] == kind:
                    discovered[key].update(urls)
        except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
            errors.append({'page': page, 'error': str(exc)})
    urls_to_verify = set().union(*discovered.values()) if discovered else set()
    urls_to_verify.update(r['url'].strip() for r in original if r['url'].strip())
    verification = {}
    url_to_key = {}
    for key, urls in discovered.items():
        for url in urls:
            url_to_key.setdefault(url, key)
    for r in original:
        if r['url'].strip():
            url_to_key.setdefault(r['url'].strip(), (r['kind'], int(r['year'])))
    for url in sorted(urls_to_verify):
        kind, year = url_to_key[url]
        if not safe_url(url, PAGES[kind]):
            verification[url] = ('invalid', 'Previously registered URL is not an allowed official HTTPS PDF')
        else:
            verification[url] = verify_pdf(url, kind, year)
    report = build_report(original, discovered, verification)
    with open('sources_candidates.csv', 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(report)
    counts = {status: sum(r['status'] == status for r in report) for status in ('document_verified', 'pdf_verified', 'unverified', 'ambiguous', 'invalid', 'missing')}
    Path('discovery_diagnostics.json').write_text(json.dumps({'version': '0.4', 'total_expected': len(report), 'counts': counts, 'page_errors': errors, 'notes': ['sources.csv unchanged', 'PDF signature alone is not document verification', 'Ambiguous URLs require manual review']}, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(counts, ensure_ascii=False))
    if errors:
        print('Index retrieval errors:', errors)


if __name__ == '__main__':
    main()
