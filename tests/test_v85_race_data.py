
import csv
import sqlite3
import tempfile
import unittest

from pathlib import Path

from v85_race_data import (
    init,
    import_starts,
    import_results,
    status,
)


URL = "https://www.travsport.se/sport"


class RaceDataTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.folder = Path(self.temp.name)
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)

        self.db.execute("PRAGMA foreign_keys=ON")
        init(self.db)

    def save(self, filename, headers, rows):
        path = self.folder / filename

        with path.open(
            "w",
            encoding="utf-8",
            newline="",
        ) as file:
            writer = csv.writer(file)
            writer.writerow(headers)
            writer.writerows(rows)

        return path

    def starts(self, scratched="0"):
        return self.save(
            "starts.csv",
            [
                "date",
                "track",
                "division",
                "start_number",
                "horse",
                "driver",
                "scratched",
                "source_url",
            ],
            [
                [
                    "2026-10-24",
                    "ExampleTrack",
                    "1",
                    "4",
                    "Horse A",
                    "Driver A",
                    scratched,
                    URL,
                ]
            ],
        )

    def result(self, number="4"):
        return self.save(
            "results.csv",
            [
                "date",
                "track",
                "division",
                "winning_number",
                "source_url",
            ],
            [
                [
                    "2026-10-24",
                    "ExampleTrack",
                    "1",
                    number,
                    URL,
                ]
            ],
        )

    def test_start_import(self):
        self.assertEqual(
            import_starts(self.db, self.starts()),
            1,
        )

        self.assertEqual(
            status(self.db),
            {
                "meetings": 1,
                "starters": 1,
                "results": 0,
            },
        )

    def test_idempotent(self):
        path = self.starts()

        import_starts(self.db, path)
        import_starts(self.db, path)

        self.assertEqual(
            status(self.db)["starters"],
            1,
        )

    def test_import_result(self):
        import_starts(self.db, self.starts())

        self.assertEqual(
            import_results(self.db, self.result()),
            1,
        )

        self.assertEqual(
            status(self.db)["results"],
            1,
        )

    def test_unknown_winner_rejected(self):
        import_starts(self.db, self.starts())

        with self.assertRaisesRegex(
            ValueError,
            "Unknown winning starter",
        ):
            import_results(
                self.db,
                self.result("99"),
            )

    def test_scratched_winner_rejected(self):
        import_starts(
            self.db,
            self.starts("1"),
        )

        with self.assertRaisesRegex(
            ValueError,
            "scratched",
        ):
            import_results(
                self.db,
                self.result(),
            )

    def test_conflicting_start_rejected(self):
        import_starts(
            self.db,
            self.starts(),
        )

        with self.assertRaisesRegex(
            ValueError,
            "changed",
        ):
            import_starts(
                self.db,
                self.starts("1"),
            )

    def test_no_unapproved_domain(self):
        path = self.save(
            "starts.csv",
            [
                "date",
                "track",
                "division",
                "start_number",
                "horse",
                "driver",
                "scratched",
                "source_url",
            ],
            [
                [
                    "2026-10-24",
                    "X",
                    "1",
                    "1",
                    "A",
                    "B",
                    "0",
                    "https://example.com/",
                ]
            ],
        )

        with self.assertRaisesRegex(
            ValueError,
            "Unapproved",
        ):
            import_starts(self.db, path)

    def test_duplicate_starter_rejected(self):
        path = self.save(
            "starts.csv",
            [
                "date",
                "track",
                "division",
                "start_number",
                "horse",
                "driver",
                "scratched",
                "source_url",
            ],
            [
                [
                    "2026-10-24",
                    "X",
                    "1",
                    "1",
                    "A",
                    "B",
                    "0",
                    URL,
                ],
                [
                    "2026-10-24",
                    "X",
                    "1",
                    "1",
                    "A",
                    "B",
                    "0",
                    URL,
                ],
            ],
        )

        with self.assertRaisesRegex(
            ValueError,
            "Duplicate starter",
        ):
            import_starts(self.db, path)


if __name__ == "__main__":
    unittest.main()
