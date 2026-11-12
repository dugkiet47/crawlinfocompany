"""Synthetic regression fixtures; this suite never accesses live websites."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import requests
from bs4 import BeautifulSoup
import crawl
from scraper import MasoThueScraper, DataMismatchError, SourceBlockedError, normalize_tax_id

BASE = 'https://masothue.com'
LIST = BASE + '/tra-cuu-ma-so-thue-theo-tinh/ha-noi-7'
PARENT = '0100000001'
BRANCH = PARENT + '-001'

def soup(html): return BeautifulSoup(html, 'lxml')

def detail(tax=PARENT, name='CÔNG TY MINH HỌA', heading_tax=None):
    return f'''<h1>{heading_tax or tax} - {name}</h1><table class="table-taxinfo">
      <tr><th itemprop="name">{name}</th></tr>
      <tr><td>Mã số thuế</td><td itemprop="taxID">{tax}</td></tr>
      <tr><td>Địa chỉ</td><td>Địa chỉ minh họa</td></tr></table>'''

def listing(*taxes):
    return ''.join(f'<div data-prefetch="/{tax}-minh-hoa"><h3><a href="/{tax}-minh-hoa">CÔNG TY MINH HỌA</a></h3></div>' for tax in taxes)

def response(url, html='', status=200, location=None):
    r = requests.Response()
    r.url, r.status_code, r.encoding = url, status, 'utf8'
    r._content, r._content_consumed = html.encode('utf8'), True
    if location: r.headers['Location'] = location
    return r

class ScraperTests(unittest.TestCase):
    def setUp(self):
        self.engine = MasoThueScraper(delay=0)
        self.engine.session.get = Mock(side_effect=AssertionError('No unmocked network'))

    def test_branch_listing_does_not_collapse_into_parent(self):
        rows = self.engine._parse_listing(soup(listing(PARENT, BRANCH, BRANCH)), LIST)
        self.assertEqual([r['tax_id'] for r in rows], [PARENT, BRANCH])

    def test_branch_detail_and_name(self):
        row = self.engine._parse_detail_page(soup(detail(BRANCH, 'CHI NHÁNH MINH HỌA')))
        self.assertEqual((row['tax_id'], row['company_name']), (BRANCH, 'CHI NHÁNH MINH HỌA'))

    def test_compact_branch_and_invalid_ids(self):
        self.assertEqual(normalize_tax_id('0100000001001'), BRANCH)
        for invalid in ('010000000', '01000000012', '01000000010011', 'abc', '１２３４５６７８９０'):
            self.assertIsNone(normalize_tax_id(invalid))

    def test_conflicting_heading_is_not_accepted(self):
        with self.assertRaises(DataMismatchError):
            self.engine._parse_detail_page(soup(detail(PARENT, heading_tax='0100000002')))

    def test_invalid_tax_table_does_not_fall_back_to_heading(self):
        with self.assertRaises(DataMismatchError):
            self.engine._parse_detail_page(soup(detail('invalid', heading_tax=PARENT)))

    def test_invalid_numeric_query_does_not_make_request(self):
        with self.assertRaises(ValueError): self.engine.search('01000000012')
        self.engine.session.get.assert_not_called()

    def test_heading_fallback_preserves_branch(self):
        row = self.engine._parse_detail_page(soup(f'<h1>{BRANCH} - CHI NHÁNH</h1><table class="table-taxinfo"></table>'))
        self.assertEqual(row, {'tax_id': BRANCH, 'company_name': 'CHI NHÁNH'})

    def test_wrong_search_redirect_is_rejected(self):
        with patch.object(self.engine, '_soup', return_value=soup(detail('0100000002'))):
            with self.assertRaises(DataMismatchError): self.engine.search(PARENT)

    def test_search_only_returns_exact_tax_match(self):
        with patch.object(self.engine, '_soup', return_value=soup(listing(PARENT, BRANCH))):
            self.assertEqual([r['tax_id'] for r in self.engine.search(PARENT)], [PARENT])
            self.assertEqual(len(self.engine.search('Minh Họa')), 2)

    def test_detail_checks_url_and_explicit_tax(self):
        with patch.object(self.engine, '_soup', return_value=soup(detail('0100000002'))):
            with self.assertRaises(DataMismatchError): self.engine.get_company_detail(BASE + '/' + PARENT + '-minh-hoa')
            with self.assertRaises(DataMismatchError): self.engine.get_company_detail(BASE + '/lookup', expected_tax_id=PARENT)

    def test_provinces_deduplicate_url_and_reject_district_external(self):
        html = f'<a href="{LIST}">Hà Nội</a><a href="{LIST}/">Tên khác</a><a href="{LIST}/quan-1">Quận</a><a href="https://other.example/tra-cuu-ma-so-thue-theo-tinh/x">External</a>'
        with patch.object(self.engine, '_soup', return_value=soup(html)):
            self.assertEqual(self.engine.get_provinces(), [('Hà Nội', LIST)])

    def test_listing_rejects_external_company(self):
        html = listing(PARENT) + '<div data-prefetch="https://other.example/0100000002-foo"><h3><a>External</a></h3></div>'
        self.assertEqual(len(self.engine._parse_listing(soup(html), LIST)), 1)

    def test_pagination_stays_on_listing_and_preserves_filters(self):
        url = LIST + '?filter=a'
        for href in ('https://other.example/?page=2', '/other?page=2', '?page=2', '?filter=b&page=2', '?filter=a&page=2&page=3', '?filter=a&page=3'):
            self.assertIsNone(self.engine._next_page_url(soup(f'<a href="{href}">Next</a>'), 1, url), href)
        self.assertEqual(self.engine._next_page_url(soup('<a href="?filter=a&page=2">2</a>'), 1, url), url + '&page=2')

    def test_crawl_uses_observed_next_link_and_deduplicates(self):
        url = LIST + '?filter=a'
        pages = [soup(listing(PARENT) + '<a href="?filter=a&page=2">2</a>'), soup(listing(PARENT, BRANCH))]
        with patch.object(self.engine, '_soup', side_effect=pages) as fetch:
            with contextlib.redirect_stdout(io.StringIO()): rows = list(self.engine.crawl_province(url, max_pages=2))
        self.assertEqual([r['tax_id'] for r in rows], [PARENT, BRANCH])
        self.assertEqual(fetch.call_args_list[1].args, (url + '&page=2',))

    def test_terminal_http_status_has_no_retry(self):
        for status in (403, 429, 404):
            self.engine.session.get.reset_mock()
            self.engine.session.get.side_effect = None
            self.engine.session.get.return_value = response(LIST, status=status)
            with self.assertRaises(requests.RequestException): self.engine._get(LIST)
            self.assertEqual(self.engine.session.get.call_count, 1)

    def test_challenge_has_no_retry(self):
        self.engine.session.get.side_effect = None
        self.engine.session.get.return_value = response(LIST, '<title>Just a moment...</title>')
        with self.assertRaises(SourceBlockedError): self.engine._get(LIST)
        self.assertEqual(self.engine.session.get.call_count, 1)

    def test_redirect_is_rate_limited_and_external_not_requested(self):
        self.engine.delay = 10
        self.engine.session.get.side_effect = [response(LIST, status=302, location='?page=2'), response(LIST+'?page=2', '<html>ok</html>')]
        with patch('scraper.time.sleep') as sleep, patch('scraper.time.monotonic', return_value=100): self.engine._get(LIST)
        self.assertEqual(sleep.call_args.args, (10,))
        self.engine.session.get.reset_mock()
        self.engine.delay = 0
        self.engine.session.get.side_effect = [response(LIST, status=302, location='https://other.example/')]
        with self.assertRaises(ValueError): self.engine._get(LIST)
        self.assertEqual(self.engine.session.get.call_count, 1)

    def test_transient_error_retries(self):
        self.engine.session.get.side_effect = [response(LIST, status=503), response(LIST, '<html>ok</html>')]
        self.assertEqual(self.engine._get(LIST).status_code, 200)
        self.assertEqual(self.engine.session.get.call_count, 2)

    def test_cli_bounded_all_listing_detail_export(self):
        urls = []
        directory = '/tra-cuu-ma-so-thue-theo-tinh'
        def send(session, req, **kwargs):
            urls.append(req.url)
            if req.url.endswith(directory): return response(req.url, f'<a href="{LIST}">Hà Nội</a>')
            if req.url == LIST: return response(req.url, listing(PARENT, BRANCH))
            return response(req.url, detail(PARENT))
        with tempfile.TemporaryDirectory() as tmp, patch('requests.Session.send', send), patch('exporter.OUTPUT_DIR', tmp), patch('sys.argv', ['crawl.py','all','--province','ha-noi','--max-pages','1','--max-records','1','--detail','--delay','0']):
            with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(crawl.main(), 0)
            self.assertEqual(len(list(Path(tmp).glob('*.csv'))), 1)
            self.assertEqual(len(list(Path(tmp).glob('*.xlsx'))), 1)
        self.assertEqual(urls, [BASE+directory, LIST, BASE+'/'+PARENT+'-minh-hoa'])

    def test_cli_mismatch_fails_without_export(self):
        with patch.object(MasoThueScraper, 'search', side_effect=DataMismatchError('Wrong tax ID')), patch('crawl._export') as export, patch('sys.argv', ['crawl.py','search',PARENT]):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()): self.assertEqual(crawl.main(), 1)
            export.assert_not_called()

if __name__ == '__main__': unittest.main()
