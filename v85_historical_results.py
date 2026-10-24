
"""Pulse Sjöden: auditable historical race results (not V85 division mapping).

Import normalized race-result CSV including shared first place. Preserve source
identity and reject conflicting reimports; do not rewrite existing V85 code.
"""
import argparse
import csv
import json
import sqlite3
from datetime import date
from pathlib import Path

FIELDS = ('date', 'track', 'race_number', 'finish_position', 'start_number',
          'horse', 'driver', 'trainer', 'start_lane_distance', 'time', 'shoes', 'cart')
SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS races (
 race_id TEXT PRIMARY KEY, race_date TEXT NOT NULL, track TEXT NOT NULL,
 race_number INTEGER NOT NULL CHECK(race_number > 0),
 source_label TEXT NOT NULL,
 UNIQUE(race_date,track,race_number)
);
CREATE TABLE IF NOT EXISTS finishers (
 race_id TEXT NOT NULL REFERENCES races(race_id),
 start_number INTEGER NOT NULL CHECK(start_number > 0),
 position TEXT NOT NULL, horse TEXT NOT NULL, driver TEXT NOT NULL,
 trainer TEXT NOT NULL, start_lane_distance TEXT NOT NULL,
 recorded_time TEXT NOT NULL, shoes TEXT NOT NULL, cart TEXT NOT NULL,
 PRIMARY KEY(race_id,start_number)
);
'''


def read_rows(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not set(FIELDS).issubset(reader.fieldnames):
            raise ValueError('Missing CSV headers: ' + ', '.join(FIELDS))
        rows = list(reader)
    if not rows:
        raise ValueError('Empty CSV')
    return rows


def ingest(db, csv_path, source_label):
    if not source_label or not source_label.strip():
        raise ValueError('A meaningful source label is required')
    rows = read_rows(csv_path)
    prepared = []
    per_race = {}
    seen = set()
    for line_no, raw in enumerate(rows, 2):
        try:
            day = date.fromisoformat(raw['date'].strip()).isoformat()
            track = raw['track'].strip()
            race_no = int(raw['race_number'])
            starter = int(raw['start_number'])
            position = raw['finish_position'].strip().lower()
            horse = raw['horse'].strip()
            driver = raw['driver'].strip()
            if not track or race_no <= 0 or starter <= 0 or not horse:
                raise ValueError('Invalid race, horse, driver or start number')
            if position not in {'', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12', '13', '14', '15', '16', '17', '18', '19', '20', 'd', 'u', 's', 'ej'}:
                raise ValueError('Unknown finish-position value: ' + position)
            race_id = f'{day}|{track.casefold()}|{race_no}'
            key = (race_id, starter)
            if key in seen:
                raise ValueError('Duplicate starter')
            seen.add(key)
            per_race.setdefault(race_id, {'winners': 0, 'date': day, 'track': track,
                                          'number': race_no})
            if position == '1':
                per_race[race_id]['winners'] += 1
            other = tuple((raw[k] or '').strip() for k in FIELDS[7:])
            prepared.append((race_id, starter, position, horse, driver, *other))
        except (ValueError, TypeError, AttributeError, KeyError) as exc:
            raise ValueError(f'CSV row {line_no}: {exc}') from exc
    for race_id, meta in per_race.items():
        if meta['winners'] < 1:
            raise ValueError(f'Race {race_id} has no first-place finisher')
    with db:
        for race_id, meta in per_race.items():
            previous = db.execute('SELECT source_label FROM races WHERE race_id=?',
                                  (race_id,)).fetchone()
            if previous and previous[0] != source_label:
                raise ValueError(f'Conflicting source label for {race_id}')
            db.execute('INSERT OR IGNORE INTO races VALUES (?,?,?,?,?)',
                       (race_id, meta['date'], meta['track'], meta['number'], source_label))
        for row in prepared:
            previous = db.execute(
                'SELECT position,horse,driver,trainer,start_lane_distance,recorded_time,shoes,cart '
                'FROM finishers WHERE race_id=? AND start_number=?', row[:2]).fetchone()
            if previous is not None and previous != row[2:]:
                raise ValueError(f'Conflicting result: {row[0]} starter {row[1]}')
            db.execute('INSERT OR IGNORE INTO finishers VALUES (?,?,?,?,?,?,?,?,?,?)', row)
    return {'races': len(per_race), 'horse_rows': len(prepared),
            'first_place_rows': sum(meta['winners'] for meta in per_race.values()),
            'races_with_shared_first': sum(meta['winners'] > 1 for meta in per_race.values()),
            'note': 'Race numbers are NOT automatically V85 divisions'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv', required=True)
    parser.add_argument('--db', default='historical_races.sqlite3')
    parser.add_argument('--source-label', required=True)
    args = parser.parse_args()
    with sqlite3.connect(args.db) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.executescript(SCHEMA)
        result = ingest(db, args.csv, args.source_label)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
