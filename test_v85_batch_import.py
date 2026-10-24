
"""Tests for Pulse Sjöden historical batch import."""

import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from v85_batch_import import (
    collect_files,
    import_batch,
)
from v85_historical_results import FIELDS


class BatchImportTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.database = self.folder / "history.sqlite3"

    def make_csv(self, name, race=1, horse="Horse A"):
        path = self.folder / name

        record = {
            "date": "2026-10-24",
            "track": "Jägersro",
            "race_number": str(race),
            "finish_position": "1",
            "start_number": "4",
            "horse": horse,
            "driver": "Test Driver",
            "trainer": "Test Trainer",
            "start_lane_distance": "4/2140",
            "time": "14,5a",
            "shoes": "Skor runt om",
            "cart": "S",
        }

        with path.open(
            "w",
            encoding="utf-8",
            newline="",
        ) as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=FIELDS,
            )
            writer.writeheader()
            writer.writerow(record)

        return path

    def database_counts(self):
        with sqlite3.connect(self.database) as db:
            races = db.execute(
                "SELECT COUNT(*) FROM races"
            ).fetchone()[0]

            horses = db.execute(
                "SELECT COUNT(*) FROM finishers"
            ).fetchone()[0]

        return races, horses

    def test_single_file(self):
        first = self.make_csv("race1.csv")

        result = import_batch(
            self.database,
            [first],
        )

        self.assertEqual(result["files_imported"], 1)
        self.assertEqual(self.database_counts(), (1, 1))

    def test_multiple_files(self):
        first = self.make_csv("race1.csv", race=1)
        second = self.make_csv("race2.csv", race=2)

        result = import_batch(
            self.database,
            [first, second],
        )

        self.assertEqual(result["files_imported"], 2)
        self.assertEqual(self.database_counts(), (2, 2))

    def test_reimport_no_duplicates(self):
        first = self.make_csv("race1.csv")

        import_batch(self.database, [first])
        import_batch(self.database, [first])

        self.assertEqual(self.database_counts(), (1, 1))

    def test_failed_batch_keeps_old_database(self):
        original = self.make_csv("original.csv", race=1)
        import_batch(self.database, [original])

        valid = self.make_csv("valid.csv", race=2)
        conflict = self.make_csv(
            "conflict.csv",
            race=1,
            horse="Different Horse",
        )

        with self.assertRaises(ValueError):
            import_batch(
                self.database,
                [valid, conflict],
            )

        self.assertEqual(self.database_counts(), (1, 1))

    def test_no_files_rejected(self):
        with self.assertRaises(ValueError):
            import_batch(self.database, [])

        self.assertFalse(self.database.exists())

    def test_collect_files(self):
        first = self.make_csv("race1.csv")
        second = self.make_csv("race2.csv", race=2)

        files = collect_files(
            [first],
            [str(self.folder / "*.csv")],
        )

        self.assertEqual(len(files), 2)
        self.assertIn(first.resolve(), files)
        self.assertIn(second.resolve(), files)


if __name__ == "__main__":
    unittest.main()
