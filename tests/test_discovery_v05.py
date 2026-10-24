import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from discover_sources import (
    PARTS_2010, build_inventory, inspect_pdf_pages, read_seed,
    safe_url, summarize_2010, verify_pdf,
)

BASE = 'https://media-cdn.travsport.se/doc/aarsstatistik-2010-'

class DummyPage:
    def __init__(self, text): self.text = text
    def extract_text(self): return self.text
class DummyReader:
    def __init__(self, texts): self.pages = [DummyPage(x) for x in texts]

class DiscoveryV05Tests(unittest.TestCase):
    def test_seed_blank_line_and_bom(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'seed.csv'
            p.write_text('\n\ufeffkind,year,part,url,status\nannual_statistics,2002,,https://media-cdn.travsport.se/x/aarsstatistik-2002.pdf,unverified\n',encoding='utf-8')
            with self.assertRaises(ValueError): read_seed(p) # BOM after newline is malformed, reject
            p.write_text('\ufeff\nkind,year,part,url,status\nannual_statistics,2002,,https://media-cdn.travsport.se/x/aarsstatistik-2002.pdf,unverified\n', encoding='utf-8')
            self.assertEqual(len(read_seed(p)), 1)
    def test_seed_duplicate_part_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'seed.csv'
            p.write_text('kind,year,part,url,status\nannual_statistics,2010,aktiva,https://media-cdn.travsport.se/a/2010.pdf,x\nannual_statistics,2010,aktiva,https://media-cdn.travsport.se/b/2010.pdf,x\n',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'duplicate'): read_seed(p)
    def test_ssrf_host_rejected(self):
        self.assertIsNone(safe_url('https://fake-travsport.se/x.pdf','https://www.travsport.se/'))
    def test_2010_aggregate_success(self):
        records=[dict(part=p,status='document_verified') for p in PARTS_2010]
        self.assertEqual(summarize_2010(records)[0], 'document_verified')
    def test_2010_aggregate_invalid(self):
        records=[dict(part=p,status='invalid' if p=='aktiva' else 'document_verified') for p in PARTS_2010]
        self.assertEqual(summarize_2010(records)[0], 'invalid')
    def test_2010_missing_part_not_approved(self):
        self.assertEqual(summarize_2010([dict(part='aktiva',status='document_verified')])[0], 'ambiguous')
    def test_2010_inventory_rollup(self):
        parts={part:BASE+part+'.pdf' for part in PARTS_2010}
        checks={('annual_statistics',2010,url):('document_verified','ok') for url in parts.values()}
        rows,details=build_inventory([{'kind':'annual_statistics','year':'2010','url':''}],{('annual_statistics',2010):parts},{},checks)
        self.assertEqual(rows[0]['status'],'document_verified')
        self.assertEqual(len(details),3)
    def test_late_page_document_found(self):
        reader=DummyReader(['nonmatching words']*14+['Ãrsredovisning 2018'])
        self.assertEqual(inspect_pdf_pages(reader,'annual_report',2018)[0],'document_verified')
    def test_wrong_year_not_document_verified(self):
        self.assertEqual(inspect_pdf_pages(DummyReader(['Ãrsredovisning 2017']),'annual_report',2018)[0],'pdf_verified')
    def test_no_text_not_document_verified(self):
        self.assertEqual(inspect_pdf_pages(DummyReader(['']),'annual_report',2018)[0],'pdf_verified')
    def test_unsafe_pdf_rejected_without_network(self):
        self.assertEqual(verify_pdf('https://evil.example/test.pdf','annual_report',2020)[0],'invalid')
    def test_same_slot_two_urls_ambiguous(self):
        u1='https://media-cdn.travsport.se/x/aarsstatistik-2018.pdf'
        u2='https://media-cdn.travsport.se/y/aarsstatistik-2018.pdf'
        rows,_=build_inventory([{'kind':'annual_statistics','year':'2018','url':u1}],{}, {('annual_statistics',2018):{u2}}, {})
        self.assertEqual(rows[0]['status'],'ambiguous')

if __name__=='__main__': unittest.main()
