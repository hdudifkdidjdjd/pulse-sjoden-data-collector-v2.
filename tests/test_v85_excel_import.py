
import unittest

from v85_excel_import import prepare_rows, safe_source


URL = "https://www.travsport.se/sport"

HEADERS = [
    "Startnr",
    "Hast",
    "Kusk",
    "Strykning",
    "Placering",
]

MAPPING = {
    "start_number": "Startnr",
    "horse": "Hast",
    "driver": "Kusk",
    "scratched": "Strykning",
    "finish_position": "Placering",
}


class V85ExcelImportTests(unittest.TestCase):

    def prepare(self, rows, kind="starts",
                mapping=None, url=URL):
        return prepare_rows(
            HEADERS,
            rows,
            mapping or MAPPING,
            kind,
            "2026-10-24",
            "Testbanan",
            1,
            url,
        )

    def starter(self, number=4, scratched="0",
                position="1"):
        return {
            "Startnr": number,
            "Hast": "Testhasten",
            "Kusk": "Testkusken",
            "Strykning": scratched,
            "Placering": position,
        }

    def test_valid_source(self):
        self.assertTrue(safe_source(URL))

    def test_unapproved_source(self):
        self.assertFalse(
            safe_source("https://example.com/data")
        )

    def test_valid_startlist(self):
        rows = self.prepare([self.starter()])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][3], 4)
        self.assertEqual(rows[0][4], "Testhasten")

    def test_scratched_horse(self):
        rows = self.prepare([
            self.starter(scratched="1")
        ])
        self.assertEqual(rows[0][6], "1")

    def test_duplicate_number_rejected(self):
        with self.assertRaises(ValueError):
            self.prepare([
                self.starter(4),
                self.starter(4),
            ])

    def test_missing_horse_rejected(self):
        row = self.starter()
        row["Hast"] = ""
        with self.assertRaises(ValueError):
            self.prepare([row])

    def test_missing_column_mapping(self):
        with self.assertRaises(ValueError):
            self.prepare(
                [self.starter()],
                mapping={"horse": "Hast"},
            )

    def test_single_winner(self):
        rows = self.prepare([
            self.starter(4, position="1"),
            self.starter(5, position="2"),
        ], kind="results")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][3], 4)

    def test_no_winner_rejected(self):
        with self.assertRaises(ValueError):
            self.prepare([
                self.starter(4, position="2")
            ], kind="results")

    def test_multiple_winners_rejected(self):
        with self.assertRaises(ValueError):
            self.prepare([
                self.starter(4, position="1"),
                self.starter(5, position="1"),
            ], kind="results")

    def test_invalid_division(self):
        with self.assertRaises(ValueError):
            prepare_rows(
                HEADERS,
                [self.starter()],
                MAPPING,
                "starts",
                "2026-10-24",
                "Testbanan",
                9,
                URL,
            )


if __name__ == "__main__":
    unittest.main()
