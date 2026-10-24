
"""Tests for Pulse Sjöden V85 Division Mapper."""

import csv
import sqlite3
import tempfile
import unittest

from pathlib import Path

from v85_division_map import (
    FIELDS,
    load_map,
    import_map,
)


SOURCE = "https://www.atg.se/spel/2026-10-24/V85"


class V85DivisionMapTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.folder = Path(self.temp.name)
        self.csv_file = self.folder / "v85_map.csv"
        self.database = self.folder / "v85_map.sqlite3"

    def make_rows(self):
        return [
            {
                "date": "2026-10-24",
                "track": "Jägersro",
                "division": str(division),
                "race_number": str(division + 4),
                "source_url": SOURCE,
            }
            for division in range(1, 9)
        ]

    def write_rows(self, rows):
        with self.csv_file.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=FIELDS,
            )
            writer.writeheader()
            writer.writerows(rows)

        return self.csv_file

    def test_valid_eight_divisions(self):
        path = self.write_rows(self.make_rows())

        rows = load_map(path)

        self.assertEqual(len(rows), 8)
        self.assertEqual(
            {row[2] for row in rows},
            set(range(1, 9)),
        )

    def test_database_import(self):
        path = self.write_rows(self.make_rows())

        result = import_map(self.database, path)

        self.assertEqual(result["divisions"], 8)

        with sqlite3.connect(self.database) as db:
            count = db.execute(
                "SELECT COUNT(*) FROM v85_division_map"
            ).fetchone()[0]

        self.assertEqual(count, 8)

    def test_reimport_without_duplicates(self):
        path = self.write_rows(self.make_rows())

        import_map(self.database, path)
        import_map(self.database, path)

        with sqlite3.connect(self.database) as db:
            count = db.execute(
                "SELECT COUNT(*) FROM v85_division_map"
            ).fetchone()[0]

        self.assertEqual(count, 8)

    def test_missing_division_rejected(self):
        rows = self.make_rows()[:-1]
        path = self.write_rows(rows)

        with self.assertRaises(ValueError):
            load_map(path)

    def test_duplicate_race_rejected(self):
        rows = self.make_rows()
        rows[1]["race_number"] = rows[0]["race_number"]

        with self.assertRaises(ValueError):
            load_map(self.write_rows(rows))

    def test_invalid_source_rejected(self):
        rows = self.make_rows()
        rows[0]["source_url"] = "https://example.com/fake"

        with self.assertRaises(ValueError):
            load_map(self.write_rows(rows))

    def test_conflicting_mapping_rejected(self):
        rows = self.make_rows()
        path = self.write_rows(rows)

        import_map(self.database, path)

        changed = self.make_rows()
        changed[0]["race_number"] = "99"
        self.write_rows(changed)

        with self.assertRaises(ValueError):
            import_map(self.database, path)

        with sqlite3.connect(self.database) as db:
            original = db.execute(
                """
                SELECT race_number
                FROM v85_division_map
                WHERE division = 1
                """
            ).fetchone()[0]

        self.assertEqual(original, 5)


if __name__ == "__main__":
    unittest.main()
