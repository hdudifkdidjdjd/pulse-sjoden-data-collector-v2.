
import unittest

from discover_sources import (
    safe_url,
    classify,
    candidates_from_html,
    build_report,
)


class DiscoveryV04Tests(unittest.TestCase):

    def test_statistics_classification(self):
        url = "https://media-cdn.travsport.se/x/aarsstatistik-2018.pdf"
        self.assertEqual(
            classify("Årsstatistik 2018", url),
            ("annual_statistics", 2018),
        )

    def test_report_classification(self):
        url = "https://media-cdn.travsport.se/x/aarsredovisning-2025.pdf"
        self.assertEqual(
            classify("", url),
            ("annual_report", 2025),
        )

    def test_report_filename_variant(self):
        url = "https://media-cdn.travsport.se/x/aarsredovning-2018.pdf"
        self.assertEqual(
            classify("", url),
            ("annual_report", 2018),
        )

    def test_reject_external_domain(self):
        url = "https://fake-travsport.se/aarsstatistik-2018.pdf"
        self.assertIsNone(
            safe_url(url, "https://www.travsport.se/")
        )

    def test_reject_non_pdf(self):
        url = "https://www.travsport.se/report.html"
        self.assertIsNone(
            safe_url(url, "https://www.travsport.se/")
        )

    def test_html_discovery(self):
        source = (
            '<a href="/aarsstatistik-2018.pdf">'
            'Årsstatistik 2018</a>'
        )
        results = candidates_from_html(
            source, "https://www.travsport.se/"
        )
        self.assertIn(
            ("annual_statistics", 2018), results
        )

    def test_ambiguous_candidates(self):
        existing = [{
            "kind": "annual_statistics",
            "year": "2018",
            "url": "https://media-cdn.travsport.se/a/aarsstatistik-2018.pdf",
        }]
        discovered = {
            ("annual_statistics", 2018): {
                "https://media-cdn.travsport.se/b/aarsstatistik-2018.pdf"
            }
        }
        result = build_report(existing, discovered, {})
        self.assertEqual(result[0]["status"], "ambiguous")
        self.assertEqual(result[0]["url"], existing[0]["url"])

    def test_missing_document(self):
        existing = [{
            "kind": "annual_report",
            "year": "2025",
            "url": "",
        }]
        result = build_report(existing, {}, {})
        self.assertEqual(result[0]["status"], "missing")


if __name__ == "__main__":
    unittest.main()
