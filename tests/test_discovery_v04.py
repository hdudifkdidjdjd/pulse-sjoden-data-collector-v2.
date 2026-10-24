import csv
import tempfile
import unittest
from pathlib import Path

from discover_sources import (
    infer_document_kind,
    infer_year,
    merge_candidate_rows,
    verify_pdf_bytes,
)


class DiscoveryV04Tests(unittest.TestCase):
    def test_kind_detection_and_year_extraction(self):
        html_like = "https://www.travsport.se/sport/statistik/arsstatistik-2018.pdf Årsstatistik 2018"
        self.assertEqual(infer_document_kind(html_like), "annual_statistics")
        self.assertEqual(infer_year(html_like, range(2001, 2020)), 2018)

        report_like = "https://www.travsport.se/arsredovisning/2019.pdf Årsredovisning 2019"
        self.assertEqual(infer_document_kind(report_like), "annual_report")
        self.assertEqual(infer_year(report_like, range(2015, 2026)), 2019)

    def test_pdf_verification_requires_document_markers(self):
        payload = (
            b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
            b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"
            + b"arsstatistik 2018"
        )
        ok, reason = verify_pdf_bytes(payload, "annual_statistics", 2018)
        self.assertTrue(ok, reason)

        bad_payload = b"%PDF-1.4\nThis is not a valid annual_statistics 2018 PDF body\n"
        ok, _ = verify_pdf_bytes(bad_payload, "annual_statistics", 2019)
        self.assertFalse(ok)

    def test_existing_urls_are_retained_and_duplicates_are_handled(self):
        existing = [
            {"kind": "annual_statistics", "year": 2018, "url": "https://example.com/retained.pdf"},
            {"kind": "annual_report", "year": 2018, "url": "https://example.com/report.pdf"},
        ]
        discovered = [
            {"kind": "annual_statistics", "year": 2018, "url": "https://new.example.com/2018.pdf", "status": "candidate", "note": "Candidate"},
            {"kind": "annual_report", "year": 2018, "url": "https://new.example.com/2018b.pdf", "status": "candidate", "note": "Candidate"},
            {"kind": "annual_report", "year": 2019, "url": "https://new.example.com/2019.pdf", "status": "candidate", "note": "Candidate"},
        ]

        merged = merge_candidate_rows(existing, discovered)
        by_key = {(row["kind"], row["year"]): row for row in merged}

        self.assertEqual(by_key[("annual_statistics", 2018)]["url"], "https://example.com/retained.pdf")
        self.assertEqual(by_key[("annual_report", 2018)]["url"], "https://example.com/report.pdf")
        self.assertTrue(("annual_report", 2019) in by_key)

    def test_candidate_csv_generation_does_not_modify_sources_csv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sources_path = root / "sources.csv"
            sources_path.write_text(
                "kind,year,url\nannual_statistics,2018,https://example.com/existing.pdf\n",
                encoding="utf-8",
            )
            from discover_sources import load_existing_sources
            rows = load_existing_sources(sources_path)
            self.assertEqual(rows[0]["url"], "https://example.com/existing.pdf")
            self.assertEqual(sources_path.read_text(encoding="utf-8").count("existing.pdf"), 1)


if __name__ == "__main__":
    unittest.main()
