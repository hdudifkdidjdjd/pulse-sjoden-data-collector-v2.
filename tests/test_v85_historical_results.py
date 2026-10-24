
import csv
import sqlite3
import tempfile
import unittest

from pathlib import Path

from v85_historical_results import (
    SCHEMA,
    FIELDS,
    ingest,
)


class HistoricalResultTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        self.path = Path(self.tmp.name) / "results.csv"

        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)

        self.db.executescript(SCHEMA)
        self.source = "user-supplied official export"

    def rows(self, winners=(1,), blank_driver=False):
        base = dict(
            date="2026-10-24",
            track="Jägersro",
            race_number="7",
            finish_position="2",
            start_number="3",
            horse="OTHER",
            driver="Test",
            trainer="",
            start_lane_distance="",
            time="",
            shoes="",
            cart="",
        )

        records = []

        for number in winners:
            row = base.copy()

            row.update(
                start_number=str(number),
                finish_position="1",
                horse=f"Horse {number}",
                driver="" if blank_driver else "Driver",
            )

            records.append(row)

        with self.path.open(
            "w",
            encoding="utf-8",
            newline="",
        ) as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=FIELDS,
            )

            writer.writeheader()
            writer.writerows(records)

        return self.path

    def test_shared_first(self):
        stats = ingest(
            self.db,
            self.rows((2, 9)),
            self.source,
        )

        self.assertEqual(
            stats["races_with_shared_first"],
            1,
        )
        self.assertEqual(
            stats["first_place_rows"],
            2,
        )

    def test_reimport_is_idempotent(self):
        path = self.rows((2, 9))

        ingest(self.db, path, self.source)
        ingest(self.db, path, self.source)

        count = self.db.execute(
            "SELECT COUNT(*) FROM finishers"
        ).fetchone()[0]

        self.assertEqual(count, 2)

    def test_conflicting_result_rolls_back(self):
        ingest(
            self.db,
            self.rows((2,)),
            self.source,
        )

        with self.assertRaises(ValueError):
            ingest(
                self.db,
                self.rows((2, 9)),
                "changed-source",
            )

        count = self.db.execute(
            "SELECT COUNT(*) FROM finishers"
        ).fetchone()[0]

        self.assertEqual(count, 1)

    def test_missing_source_rejected(self):
        with self.assertRaises(ValueError):
            ingest(
                self.db,
                self.rows((2,)),
                "",
            )

    def test_blank_driver_allowed_for_nonstarter(self):
        stats = ingest(
            self.db,
            self.rows((2,), blank_driver=True),
            self.source,
        )

        self.assertEqual(
            stats["horse_rows"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
