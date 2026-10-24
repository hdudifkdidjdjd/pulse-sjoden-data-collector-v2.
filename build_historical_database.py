
"""Historical Data Engine v0.2: auditable PDF text -> SQLite review database.

This intentionally records numeric candidates, NOT confidently classified betting
statistics. Ambiguous PDF text must be reviewed before numeric model training.
"""
import argparse
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

NUMBER = re.compile(r'(?<!\w)[+-]?(?:\d{1,3}(?:[ .]\d{3})+|\d+)(?:,\d+)?%?(?!\w)')
SCHEMA = '''
CREATE TABLE IF NOT EXISTS documents (
 document_id TEXT PRIMARY KEY, kind TEXT NOT NULL, year INTEGER NOT NULL,
 source_url TEXT NOT NULL, pdf_sha256 TEXT NOT NULL,
 UNIQUE(kind, year, source_url, pdf_sha256)
);
CREATE TABLE IF NOT EXISTS pages (
 document_id TEXT NOT NULL REFERENCES documents(document_id),
 page_number INTEGER NOT NULL CHECK(page_number > 0),
 extraction_status TEXT NOT NULL, text_sha256 TEXT NOT NULL,
 text TEXT NOT NULL, PRIMARY KEY(document_id,page_number)
);
CREATE TABLE IF NOT EXISTS numeric_candidates (
 document_id TEXT NOT NULL, page_number INTEGER NOT NULL,
 line_number INTEGER NOT NULL, token_number INTEGER NOT NULL,
 raw_value TEXT NOT NULL, source_line TEXT NOT NULL,
 review_status TEXT NOT NULL DEFAULT 'unreviewed',
 PRIMARY KEY(document_id,page_number,line_number,token_number),
 FOREIGN KEY(document_id,page_number) REFERENCES pages(document_id,page_number)
);
CREATE INDEX IF NOT EXISTS idx_candidates_value ON numeric_candidates(raw_value);
'''


def import_jsonl(input_path, database_path):
    input_path, database_path = Path(input_path), Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    stats = {'pages': 0, 'pages_with_text': 0, 'numeric_candidates': 0, 'documents': set()}
    with sqlite3.connect(database_path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.executescript(SCHEMA)
        with input_path.open(encoding='utf-8') as infile:
            for source_row, line in enumerate(infile, 1):
                if not line.strip():
                    continue
                row = json.loads(line)
                kind = row['kind']
                year = int(row['year'])
                page = int(row['page'])
                source = row['source_url']
                sha = row['sha256'].lower()
                status = row['status']
                value = row.get('text') or ''
                parsed = urlsplit(source)
                if (kind not in ('annual_statistics', 'annual_report')
                        or year < 2001 or year > 2025 or page < 1
                        or parsed.scheme != 'https'
                        or parsed.hostname not in {'media-cdn.travsport.se', 'www.travsport.se', 'travsport.se'}
                        or not re.fullmatch('[0-9a-f]{64}', sha)):
                    raise ValueError(f'Invalid provenance in input row {source_row}')
                docid = hashlib.sha256(f'{kind}\n{year}\n{source}\n{sha}'.encode()).hexdigest()
                db.execute('INSERT OR IGNORE INTO documents VALUES (?,?,?,?,?)',
                           (docid, kind, year, source, sha))
                text_sha = hashlib.sha256(value.encode()).hexdigest()
                db.execute('INSERT OR REPLACE INTO pages VALUES (?,?,?,?,?)',
                           (docid, page, status, text_sha, value))
                db.execute('DELETE FROM numeric_candidates WHERE document_id=? AND page_number=?',
                           (docid, page))
                if status == 'text_extracted':
                    stats['pages_with_text'] += 1
                    for lineno, rawline in enumerate(value.splitlines(), 1):
                        for tokenno, match in enumerate(NUMBER.finditer(rawline), 1):
                            db.execute('INSERT INTO numeric_candidates '
                                       '(document_id,page_number,line_number,token_number,raw_value,source_line) '
                                       'VALUES (?,?,?,?,?,?)',
                                       (docid,page,lineno,tokenno,match.group(),rawline[:1200]))
                            stats['numeric_candidates'] += 1
                stats['pages'] += 1
                stats['documents'].add(docid)
    return dict(documents=len(stats['documents']), pages=stats['pages'],
                pages_with_text=stats['pages_with_text'],
                numeric_candidates=stats['numeric_candidates'],
                caveat='Unreviewed numeric text tokens; not verified statistics or race predictions')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, help='*_pages.jsonl from the extraction')
    parser.add_argument('--database', default='historical_output/trav_history.sqlite3')
    parser.add_argument('--summary', default='historical_output/import_summary.json')
    args = parser.parse_args()
    report = import_jsonl(args.input, args.database)
    report_path = Path(args.summary)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
