
"""Pulse Sjöden: batch import of historical race CSV files.

Imports multiple normalized result files into a single SQLite
database without modifying the existing V85 or SAT engines.

Examples:
  python v85_batch_import.py \
    --db historical_output/races.sqlite3 \
    --files jagersro_results_2026-10-24_normalized.csv

  python v85_batch_import.py \
    --db historical_output/races.sqlite3 \
    --glob "data/*.csv"
"""

import argparse
import glob
import json
import os
import sqlite3
import tempfile

from pathlib import Path

from v85_historical_results import SCHEMA, ingest


def collect_files(paths, patterns):
    candidates = [Path(p) for p in paths]

    for pattern in patterns:
        candidates.extend(
            Path(p) for p in glob.glob(pattern)
        )

    selected = sorted({
        p.resolve() for p in candidates
    })

    if not selected:
        raise ValueError("No CSV files selected")

    for path in selected:
        if (
            not path.is_file()
            or path.suffix.lower() != ".csv"
        ):
            raise ValueError(
                f"Not an existing CSV file: {path}"
            )

    names = [p.name for p in selected]

    if len(names) != len(set(names)):
        raise ValueError(
            "Filenames must be unique "
            "to preserve source labels"
        )

    return selected


def import_batch(
    database_path,
    files,
    source_prefix="normalized-csv",
):
    database_path = Path(
        database_path
    ).resolve()

    database_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    files = [
        Path(p).resolve()
        for p in files
    ]

    if not files:
        raise ValueError(
            "No files to import"
        )

    if (
        database_path.exists()
        and not database_path.is_file()
    ):
        raise ValueError(
            "Database path is not a file"
        )

    if not source_prefix.strip():
        raise ValueError(
            "Source prefix cannot be empty"
        )

    fd, temp_name = tempfile.mkstemp(
        prefix=".v85-import-",
        suffix=".sqlite3",
        dir=database_path.parent,
    )

    os.close(fd)

    staging = Path(temp_name)
    summary = []

    try:
        with sqlite3.connect(staging) as db:
            db.execute(
                "PRAGMA foreign_keys=ON"
            )

            if database_path.exists():
                with sqlite3.connect(
                    database_path
                ) as original:
                    original.backup(db)

            db.executescript(SCHEMA)

            for path in files:
                source_label = (
                    f"{source_prefix.strip()}:"
                    f"{path.name}"
                )

                result = ingest(
                    db,
                    path,
                    source_label,
                )

                summary.append({
                    "file": path.name,
                    **result,
                })

            integrity = db.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0]

            if integrity != "ok":
                raise ValueError(
                    "SQLite integrity check failed: "
                    + str(integrity)
                )

            totals = {
                "races": db.execute(
                    "SELECT COUNT(*) FROM races"
                ).fetchone()[0],

                "horse_rows": db.execute(
                    "SELECT COUNT(*) FROM finishers"
                ).fetchone()[0],

                "first_place_rows": db.execute(
                    "SELECT COUNT(*) FROM finishers "
                    "WHERE position='1'"
                ).fetchone()[0],
            }

        os.replace(
            staging,
            database_path,
        )

        return {
            "database": str(database_path),
            "files_imported": len(summary),
            "database_totals": totals,
            "file_results": summary,
            "note": (
                "Track race numbers have NOT "
                "been mapped to V85 divisions"
            ),
        }

    finally:
        if staging.exists():
            staging.unlink()


def main():
    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "--db",
        default="historical_output/races.sqlite3",
    )

    parser.add_argument(
        "--files",
        nargs="*",
        default=[],
    )

    parser.add_argument(
        "--glob",
        action="append",
        default=[],
    )

    parser.add_argument(
        "--source-prefix",
        default="normalized-csv",
    )

    args = parser.parse_args()

    files = collect_files(
        args.files,
        args.glob,
    )

    report = import_batch(
        args.db,
        files,
        args.source_prefix,
    )

    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
