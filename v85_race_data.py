
"""Pulse Sjöden V85 Race Data v0.1.

Import reviewed start lists and official results into SQLite.
CSV inputs are explicit, provenance retained; no undocumented scraping/API.
Does not alter Source Discovery, the stable SAT solver, or sources.csv.

Usage:
  python v85_race_data.py init --db v85_data.sqlite3
  python v85_race_data.py import-starts --db v85_data.sqlite3 --csv starts.csv
  python v85_race_data.py import-results --db v85_data.sqlite3 --csv results.csv
  python v85_race_data.py status --db v85_data.sqlite3
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS meetings (
  meeting_id TEXT PRIMARY KEY,
  date TEXT NOT NULL,
  track TEXT NOT NULL,
  source_url TEXT NOT NULL,
  UNIQUE(date, track)
);
CREATE TABLE IF NOT EXISTS starters (
  meeting_id TEXT NOT NULL REFERENCES meetings(meeting_id),
  division INTEGER NOT NULL CHECK (division BETWEEN 1 AND 8),
  start_number INTEGER NOT NULL CHECK (start_number > 0),
  horse TEXT NOT NULL,
  driver TEXT NOT NULL,
  scratched INTEGER NOT NULL DEFAULT 0 CHECK (scratched IN (0,1)),
  PRIMARY KEY (meeting_id, division, start_number)
);
CREATE TABLE IF NOT EXISTS results (
  meeting_id TEXT NOT NULL,
  division INTEGER NOT NULL,
  winning_number INTEGER NOT NULL,
  source_url TEXT NOT NULL,
  PRIMARY KEY (meeting_id, division),
  FOREIGN KEY (meeting_id, division, winning_number)
    REFERENCES starters(meeting_id, division, start_number)
);
"""
START_FIELDS = ('date', 'track', 'division', 'start_number', 'horse', 'driver', 'scratched', 'source_url')
RESULT_FIELDS = ('date', 'track', 'division', 'winning_number', 'source_url')


def official_url(url: str) -> bool:
    try:
        p = urlsplit(url)
        return bool(p.scheme == 'https' and p.hostname in {'www.travsport.se', 'travsport.se', 'www.atg.se', 'atg.se'}
                    and not p.username and not p.password and p.port in (None, 443))
    except ValueError:
        return False


def clean_date(value: str) -> str:
    return dt.date.fromisoformat(value).isoformat()


def clean_division(value: str) -> int:
    v = int(value)
    if not 1 <= v <= 8:
        raise ValueError('V85 division must be 1..8')
    return v


def meeting_id(date: str, track: str) -> str:
    return f'{date}|{track.strip().casefold()}'


def read_csv(path: str | Path, required: tuple[str, ...]) -> list[dict]:
    with Path(path).open(newline='', encoding='utf-8-sig') as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not set(required).issubset(reader.fieldnames):
            raise ValueError(f'CSV requires headers: {", ".join(required)}')
        data = list(reader)
    if not data:
        raise ValueError('CSV has no records')
    return data


def init(db: sqlite3.Connection) -> None:
    db.executescript(SCHEMA)


def import_starts(db: sqlite3.Connection, path: str | Path) -> int:
    rows = read_csv(path, START_FIELDS)
    prepared = []
    seen = set()
    meeting_sources = {}
    for n, r in enumerate(rows, 2):
        try:
            date = clean_date(r['date'].strip())
            track = r['track'].strip()
            division = clean_division(r['division'])
            number = int(r['start_number'])
            horse, driver = r['horse'].strip(), r['driver'].strip()
            scratched = r['scratched'].strip().lower()
            url = r['source_url'].strip()
            if not track or not horse or not driver or number < 1:
                raise ValueError('Required text missing or invalid start number')
            if scratched not in {'0', '1'}:
                raise ValueError('scratched must be 0 or 1')
            if not official_url(url):
                raise ValueError('Unapproved source URL')
            mid = meeting_id(date, track)
            key = (mid, division, number)
            if key in seen:
                raise ValueError('Duplicate starter')
            seen.add(key)
            if mid in meeting_sources and meeting_sources[mid] != url:
                raise ValueError('Meeting rows must share source URL')
            meeting_sources[mid] = url
            prepared.append((mid, date, track, division, number, horse, driver, int(scratched), url))
        except (TypeError, AttributeError, ValueError) as exc:
            raise ValueError(f'Start row {n}: {exc}') from exc
    with db:
        for mid, date, track, *_ in prepared:
            db.execute('INSERT OR IGNORE INTO meetings VALUES (?,?,?,?)',
                       (mid, date, track, meeting_sources[mid]))
        for mid, date, track, division, number, horse, driver, scratched, url in prepared:
            existing = db.execute('SELECT horse,driver,scratched FROM starters WHERE meeting_id=? AND division=? AND start_number=?',
                                  (mid, division, number)).fetchone()
            new = (horse, driver, scratched)
            if existing and existing != new:
                raise ValueError(f'Start list changed for {mid} V85-{division} #{number}; review before replacement')
            db.execute('INSERT OR IGNORE INTO starters VALUES (?,?,?,?,?,?)',
                       (mid, division, number, horse, driver, scratched))
    return len(prepared)


def import_results(db: sqlite3.Connection, path: str | Path) -> int:
    rows = read_csv(path, RESULT_FIELDS)
    prepared = []
    seen = set()
    for n, r in enumerate(rows, 2):
        try:
            date = clean_date(r['date'].strip())
            track = r['track'].strip()
            division = clean_division(r['division'])
            number = int(r['winning_number'])
            url = r['source_url'].strip()
            if not track or number < 1 or not official_url(url):
                raise ValueError('Invalid result details or source URL')
            mid = meeting_id(date, track)
            if (mid, division) in seen:
                raise ValueError('Duplicate division result')
            seen.add((mid, division))
            prepared.append((mid, division, number, url))
        except (TypeError, AttributeError, ValueError) as exc:
            raise ValueError(f'Result row {n}: {exc}') from exc
    with db:
        for mid, division, number, url in prepared:
            starter = db.execute('SELECT scratched FROM starters WHERE meeting_id=? AND division=? AND start_number=?',
                                 (mid, division, number)).fetchone()
            if starter is None:
                raise ValueError(f'Unknown winning starter {mid} V85-{division} #{number}')
            if starter[0]:
                raise ValueError('Winner cannot be scratched')
            old = db.execute('SELECT winning_number FROM results WHERE meeting_id=? AND division=?', (mid, division)).fetchone()
            if old and old[0] != number:
                raise ValueError('Result conflicts with previous official result')
            db.execute('INSERT OR IGNORE INTO results VALUES (?,?,?,?)', (mid, division, number, url))
    return len(prepared)


def status(db: sqlite3.Connection) -> dict:
    return {name: db.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0]
            for name in ('meetings', 'starters', 'results')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('init', 'import-starts', 'import-results', 'status'))
    parser.add_argument('--db', default='v85_data.sqlite3')
    parser.add_argument('--csv')
    args = parser.parse_args()
    if args.action.startswith('import-') and not args.csv:
        parser.error('--csv is required for import')
    with sqlite3.connect(args.db) as db:
        db.execute('PRAGMA foreign_keys=ON')
        init(db)
        if args.action == 'import-starts':
            import_starts(db, args.csv)
        elif args.action == 'import-results':
            import_results(db, args.csv)
        print(json.dumps(status(db), ensure_ascii=False))


if __name__ == '__main__':
    main()
