import csv
import tempfile
import unittest
from pathlib import Path
from collector.__main__ import load_sources

ROOT = Path(__file__).resolve().parents[1]

class SourceTests(unittest.TestCase):
    def test_coverage(self):
        rows = load_sources(ROOT / "sources.csv")
        self.assertEqual(len(rows), 30)
        self.assertEqual(sum(bool(row["url"]) for row in rows), 2)

    def test_duplicate_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sources.csv"
            path.write_text((ROOT / "sources.csv").read_text(encoding="utf-8") + "annual_report,2018,\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_sources(path)

    def test_insecure_url_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sources.csv"
            content = (ROOT / "sources.csv").read_text(encoding="utf-8")
            path.write_text(content.replace("https://media-cdn", "http://media-cdn", 1), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_sources(path)

if __name__ == "__main__":
    unittest.main()
