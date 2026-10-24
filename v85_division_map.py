
"""Pulse Sjöden: verified V85 division mapping.

Maps V85 divisions 1-8 to real track race numbers.
Mappings must be verified and supplied in a CSV file.

Does not change the existing SAT engine or race tables.
"""

import argparse
import csv
import datetime
import json
import sqlite3

from pathlib import Path
from urllib.parse import urlsplit


FIELDS = (
    "date",
    "track",
    "division",
    "race_number",
    "source_url",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS v85_division_map (
    date TEXT NOT NULL,
    track TEXT NOT NULL,
    division INTEGER NOT NULL
        CHECK(division BETWEEN 1 AND 8),
    race_number INTEGER NOT NULL
        CHECK(race_number > 0),
    source_url TEXT NOT NULL,
    PRIMARY KEY(date, track, division),
    UNIQUE(date, track, race_number)
);
"""


def valid_source(value):
    try:
        parsed = urlsplit(value)

        return (
            parsed.scheme == "https"
            and parsed.hostname in {
                "atg.se",
                "www.atg.se",
                "travsport.se",
                "www.travsport.se",
            }
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 443)
        )

    except ValueError:
        return False


def load_map(path):
    with Path(path).open(
        encoding="utf-8-sig",
        newline="",
    ) as handle:

        reader = csv.DictReader(handle)

        if (
            not reader.fieldnames
            or not set(FIELDS).issubset(
                reader.fieldnames
            )
        ):
            raise ValueError(
                "Required CSV columns: "
                + ", ".join(FIELDS)
            )

        raw_rows = list(reader)

    if len(raw_rows) != 8:
        raise ValueError(
            "Expected exactly eight V85 divisions, "
            f"found {len(raw_rows)}"
        )

    rows = []

    for lineno, raw in enumerate(raw_rows, 2):
        try:
            day = datetime.date.fromisoformat(
                raw["date"].strip()
            ).isoformat()

            track = raw["track"].strip()
            division = int(raw["division"])
            race_number = int(raw["race_number"])
            url = raw["source_url"].strip()

            if (
                not track
                or division not in range(1, 9)
                or race_number < 1
                or not valid_source(url)
            ):
                raise ValueError(
                    "Invalid track, division, "
                    "race number, or source URL"
                )

            rows.append((
                day,
                track,
                division,
                race_number,
                url,
            ))

        except (
            KeyError,
            TypeError,
            AttributeError,
            ValueError,
        ) as error:
            raise ValueError(
                f"CSV row {lineno}: {error}"
            ) from error

    meetings = {
        (row[0], row[1])
        for row in rows
    }

    if len(meetings) != 1:
        raise ValueError(
            "All divisions must belong to "
            "the same date and track"
        )

    divisions = {
        row[2]
        for row in rows
    }

    if divisions != set(range(1, 9)):
        raise ValueError(
            "V85 divisions must be exactly 1-8"
        )

    race_numbers = {
        row[3]
        for row in rows
    }

    if len(race_numbers) != 8:
        raise ValueError(
            "Every division must map "
            "to a different track race"
        )

    return rows


def import_map(database, csv_path):
    rows = load_map(csv_path)

    with sqlite3.connect(database) as db:
        db.executescript(SCHEMA)

        with db:
            for row in rows:
                old = db.execute(
                    """
                    SELECT race_number, source_url
                    FROM v85_division_map
                    WHERE date=?
                      AND track=?
                      AND division=?
                    """,
                    row[:3],
                ).fetchone()

                if (
                    old is not None
                    and old != row[3:]
                ):
                    raise ValueError(
                        "Conflicting existing mapping: "
                        f"V85-{row[2]}"
                    )

                db.execute(
                    """
                    INSERT OR IGNORE
                    INTO v85_division_map
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    row,
                )

    return {
        "date": rows[0][0],
        "track": rows[0][1],
        "divisions": len(rows),
        "note": (
            "Verified mapping, not inferred "
            "from track race numbers"
        ),
    }


def main():
    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "--csv",
        required=True,
    )

    parser.add_argument(
        "--db",
        default=(
            "historical_output/"
            "v85_divisions.sqlite3"
        ),
    )

    args = parser.parse_args()

    path = Path(args.db)

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    result = import_map(
        path,
        args.csv,
    )

    print(
        json.dumps(
            result,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
