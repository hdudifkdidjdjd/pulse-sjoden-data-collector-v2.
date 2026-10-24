
"""Tests for Historical Data Engine v0.2."""

import hashlib
import json
import sqlite3
import tempfile
import unittest

from pathlib import Path

from build_historical_database import import_jsonl


class HistoricalDatabaseTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.folder = Path(self.temp.name)
        self.input = self.folder / "pages.jsonl"
        self.database = self.folder / "history.sqlite3"

    def make_record(
        self,
        text="Årsstatistik 2019\nHästar 123",
        status="text_extracted",
        url=None,
        sha=None,
    ):
        return {
            "kind": "annual_statistics",
            "year": 2019,
            "page": 1,
            "source_url": url or (
                "https://media-cdn.travsport.se/"
                "sqxbl3ac/aarsstatistik-2019.pdf"
            ),
            "sha256": sha or hashlib.sha256(
                b"test-pdf"
            ).hexdigest(),
            "status": status,
            "text": text,
        }

    def write_records(self, *records):
        with self.input.open(
            "w",
            encoding="utf-8",
        ) as file:
            for record in records:
                file.write(
                    json.dumps(
                        record,
                        ensure_ascii=False,
                    ) + "\n"
                )

    def test_import_creates_database(self):
        self.write_records(self.make_record())

        result = import_jsonl(
            self.input,
            self.database,
        )

        self.assertEqual(result["documents"], 1)
        self.assertEqual(result["pages"], 1)
        self.assertEqual(result["pages_with_text"], 1)
        self.assertTrue(self.database.exists())

    def test_numeric_candidates_are_unreviewed(self):
        self.write_records(self.make_record())

        result = import_jsonl(
            self.input,
            self.database,
        )

        self.assertGreater(
            result["numeric_candidates"],
            0,
        )

        with sqlite3.connect(self.database) as db:
            rows = db.execute(
                "SELECT raw_value, review_status "
                "FROM numeric_candidates"
            ).fetchall()

        self.assertTrue(rows)
        self.assertTrue(
            all(status == "unreviewed" for _, status in rows)
        )

    def test_empty_page_produces_no_numbers(self):
        self.write_records(
            self.make_record(
                text="",
                status="needs_ocr",
            )
        )

        result = import_jsonl(
            self.input,
            self.database,
        )

        self.assertEqual(result["pages_with_text"], 0)
        self.assertEqual(result["numeric_candidates"], 0)

    def test_reimport_does_not_duplicate_records(self):
        self.write_records(self.make_record())

        import_jsonl(self.input, self.database)
        import_jsonl(self.input, self.database)

        with sqlite3.connect(self.database) as db:
            pages = db.execute(
                "SELECT COUNT(*) FROM pages"
            ).fetchone()[0]

        self.assertEqual(pages, 1)

    def test_rejects_unapproved_domain(self):
        self.write_records(
            self.make_record(
                url="https://example.com/fake.pdf"
            )
        )

        with self.assertRaises(ValueError):
            import_jsonl(
                self.input,
                self.database,
            )

    def test_rejects_invalid_sha256(self):
        self.write_records(
            self.make_record(sha="invalid")
        )

        with self.assertRaises(ValueError):
            import_jsonl(
                self.input,
                self.database,
            )


if __name__ == "__main__":
    unittest.main()
