"""Discover document URLs from Svensk Travsport's official index pages.

Produces a reviewed candidate CSV, never silently overwrites sources.csv.
"""
import csv
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

PAGES = {
    'annual_statistics': 'https://www.travsport.se/sport/statistik/arsstatistik',
    'annual_report': 'https://www.travsport.se/svensk-travsport/organisation/arsredovisning',
}

class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.href = None
        self.label = []
        self.links = []
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.href = dict(attrs).get('href')
            self.label = []
    def handle_data(self, data):
        if self.href is not None:
            self.label.append(data)
    def handle_endtag(self, tag):
        if tag == 'a' and self.href is not None:
            self.links.append((' '.join(''.join(self.label).split()), self.href))
            self.href = None


def main():
    candidates = {}
    for kind, page in PAGES.items():
        req = Request(page, headers={'User-Agent': 'PulseSjodenCollector/0.2 (+public-document-index)'})
        with urlopen(req, timeout=30) as response:
            html = response.read(5_000_000).decode('utf-8', 'replace')
        parser = Links()
        parser.feed(html)
        for label, href in parser.links:
            match = re.search(r'års(?:statistik|redovisning|redov[ni]+ng)\s*(20\d\d)', label, re.I)
            if not match:
                continue
            year = int(match.group(1))
            if (kind == 'annual_statistics' and not 2001 <= year <= 2019) or (kind == 'annual_report' and not 2015 <= year <= 2025):
                continue
            url = urljoin(page, href)
            if urlsplit(url).scheme != 'https' or not urlsplit(url).hostname.endswith('.travsport.se'):
                continue
            candidates.setdefault((kind, year), []).append((label, url))

    with open('sources.csv', newline='', encoding='utf-8') as source:
        rows = list(csv.DictReader(source))
    output = Path('sources_candidates.csv')
    with output.open('w', newline='', encoding='utf-8') as dest:
        writer = csv.DictWriter(dest, fieldnames=['kind','year','url','status','note'])
        writer.writeheader()
        for row in rows:
            key = row['kind'], int(row['year'])
            matches = list(dict.fromkeys(url for label, url in candidates.get(key, [])))
            existing = row['url'].strip()
            if existing:
                writer.writerow(dict(**row, status='existing', note='Already registered; retain until separately verified'))
            elif len(matches) == 1:
                writer.writerow(dict(**{**row,'url':matches[0]}, status='candidate', note='Found on official index; verify PDF before adoption'))
            elif len(matches) > 1:
                writer.writerow(dict(**row, status='ambiguous', note=' | '.join(matches)))
            else:
                writer.writerow(dict(**row, status='not_found', note='No unambiguous link on official index'))
    print(f'Wrote {output}; inspect candidate links before updating sources.csv')

if __name__ == '__main__':
    main()
