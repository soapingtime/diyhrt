# SPDX-License-Identifier: GPL-3.0-only

import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import functools
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import io

from warcio.statusandheaders import StatusAndHeaders
from warcio.warcwriter import WARCWriter

from playwright.sync_api import Error as PlaywrightError

from archive_app import Capture, is_capture_request, scroll_page


class AppArchiveTests(unittest.TestCase):
    def test_page_exclusions_apply_to_discovery_and_asset_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            capture = Capture(temp, 'valerie.vg', r'/(login|register|profile)(/|$|[?])')
            public = capture.origin + 'meds/products/?region=EU'
            excluded = [
                capture.origin + 'login?next=/profile',
                capture.origin + 'register',
                capture.origin + 'profile/',
                capture.origin + 'cdn-cgi/challenge-platform/help',
                'https://developers.cloudflare.com/help/',
            ]
            self.assertTrue(capture.page_allowed(public))
            for url in excluded:
                self.assertFalse(capture.page_allowed(url), url)
            links = ''.join('<a href="' + url + '">link</a>' for url in [public] + excluded)
            capture.record(
                capture.origin,
                ('<html><head></head><body>' + links + '</body></html>').encode(),
                200,
                'text/html',
            )

            def fetch(url):
                self.assertEqual(url, public)
                capture.record(
                    url, b'<html><head></head><body>Products</body></html>', 200, 'text/html'
                )

            with patch.object(capture, 'request', side_effect=fetch) as request:
                capture.complete_assets()
            request.assert_called_once_with(public)
            self.assertEqual(set(capture.pages), {capture.origin, public})

    def test_crawl_defers_prefetches_without_dropping_public_data_or_assets(self):
        def request(url, method='GET', resource='fetch'):
            return SimpleNamespace(url=url, method=method, resource_type=resource)

        self.assertTrue(is_capture_request(request('https://diyhrt.coffee/api/v1/items')))
        self.assertTrue(is_capture_request(request('https://diyhrt.coffee/_next/app.js')))
        self.assertTrue(
            is_capture_request(request('https://diyhrt.coffee/calculator', resource='document'))
        )
        self.assertFalse(is_capture_request(request('https://diyhrt.coffee/?_rsc=random')))
        self.assertFalse(is_capture_request(request('https://diyhrt.coffee/?_rsc')))
        self.assertFalse(
            is_capture_request(request('https://diyhrt.coffee/api/v1/visits', method='POST'))
        )
        self.assertFalse(
            is_capture_request(request('https://diyhrt.coffee/events', resource='eventsource'))
        )

    def test_browser_api_reads_reuse_real_anonymous_http_responses(self):
        class GuestHandler(SimpleHTTPRequestHandler):
            def log_message(self, *_arguments):
                pass

            def do_GET(self):
                self.send_response(401)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"user":null}')

        server = ThreadingHTTPServer(('127.0.0.1', 0), GuestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                capture = Capture(temp, '127.0.0.1')
                url = 'http://127.0.0.1:' + str(server.server_port) + '/api/v1/me'
                record = capture.browser_response(url)
                self.assertEqual(record['status'], 401)
                self.assertEqual(
                    (capture.directory / record['file']).read_bytes(), b'{"user":null}'
                )
                with patch.object(
                    capture.session, 'get', side_effect=AssertionError('Response was already saved')
                ):
                    self.assertEqual(capture.browser_response(url), record)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_identical_assets_import_from_warc_revisits(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'fixture.warc.gz'
            with source.open('wb') as stream:
                writer = WARCWriter(stream, gzip=True)
                headers = StatusAndHeaders(
                    '200 OK', [('Content-Type', 'image/png')], protocol='HTTP/1.1'
                )
                first = writer.create_warc_record(
                    'https://example.com/a.png',
                    'response',
                    payload=io.BytesIO(b'identical asset'),
                    http_headers=headers,
                )
                writer.write_record(first)
                revisit = writer.create_revisit_record(
                    'https://example.com/b.png',
                    first.rec_headers.get_header('WARC-Payload-Digest'),
                    'https://example.com/a.png',
                    first.rec_headers.get_header('WARC-Date'),
                    http_headers=headers,
                )
                writer.write_record(revisit)
            restored = Capture(root / 'restored', 'example.com')
            restored.import_warc(source)
            self.assertEqual(len(restored.responses), 2)
            item = restored.responses['https://example.com/b.png']
            self.assertEqual((restored.directory / item['file']).read_bytes(), b'identical asset')

    def test_document_removes_collectors_and_preserves_content(self):
        with tempfile.TemporaryDirectory() as temp:
            capture = Capture(temp, 'valerie.vg')
            body = b'''<html><head><title>Product</title></head><body>
                <p>Original product information</p><img src="" alt="Product photo unavailable">
                <span data-bs-toggle="tooltip" data-bs-title="">Visible label</span>
                <script>window.__CF$cv$params = {}; load('/cdn-cgi/challenge-platform/');</script>
                <script src="https://static.cloudflareinsights.com/beacon.js"></script>
                <script src="/app.js"></script></body></html>'''
            result = capture.document(body).decode()
            self.assertIn('Original product information', result)
            self.assertIn('Product photo unavailable', result)
            self.assertIn('Visible label', result)
            self.assertIn('/app.js', result)
            self.assertNotIn('__CF$cv$params', result)
            self.assertNotIn('cloudflareinsights', result)
            self.assertNotIn('data-bs-toggle', result)

    def test_wget_warc_keeps_nested_requisites(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            web = root / 'web'
            web.mkdir()
            files = {
                'index.html': b'<html><head><link rel="stylesheet" href="style.css"></head></html>',
                'style.css': b'@font-face { src: url(font.woff2); }',
                'font.woff2': b'font fixture',
            }
            for name, content in files.items():
                (web / name).write_bytes(content)
            handler = functools.partial(SimpleHTTPRequestHandler, directory=str(web))
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            origin = 'http://127.0.0.1:' + str(server.server_port) + '/'
            try:
                result = subprocess.run(
                    [
                        os.environ.get('DIYHRT_WGET', 'wget'),
                        '--mirror',
                        '--page-requisites',
                        '--no-parent',
                        '--warc-file=' + str(root / 'crawl'),
                        '--directory-prefix=' + str(root / 'download'),
                        origin + 'index.html',
                    ],
                    capture_output=True,
                    text=True,
                )
                self.assertIn(result.returncode, (0, 8), result.stderr)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
            capture = Capture(root / 'responses', '127.0.0.1')
            capture.import_warc(root / 'crawl.warc.gz')
            for name, expected in files.items():
                record = capture.responses[origin + name]
                self.assertEqual((capture.directory / record['file']).read_bytes(), expected)

    def test_css_requisites_are_captured_without_rewriting_the_source(self):
        with tempfile.TemporaryDirectory() as temp:
            capture = Capture(temp, 'example.com')
            html = b'<html><head><link rel="stylesheet" href="/css/main.css"></head></html>'
            capture.record(capture.origin, html, 200, 'text/html')
            capture.record(
                capture.origin + 'css/main.css',
                b'@import "nested.css"; @font-face { src: url(../font.woff2); }',
                200,
                'text/css',
            )
            replies = {
                capture.origin + 'css/nested.css': (b'p { color: red; }', 'text/css'),
                capture.origin + 'font.woff2': (b'font fixture', 'font/woff2'),
            }

            def fetch(url):
                if url not in capture.responses:
                    body, kind = replies[url]
                    capture.record(url, body, 200, kind)

            with patch.object(capture, 'request', side_effect=fetch):
                capture.complete_assets()
            self.assertEqual(len(capture.responses), 4)
            document = capture.responses[capture.origin]
            self.assertEqual((Path(temp) / document['file']).read_bytes(), html)

    def test_missing_required_asset_prevents_success(self):
        with tempfile.TemporaryDirectory() as temp:
            capture = Capture(temp, 'example.com')
            capture.record(
                capture.origin,
                b'<html><head><script src="/missing.js"></script></head></html>',
                200,
                'text/html',
            )
            capture.record(capture.origin + 'missing.js', b'not found', 404, 'text/plain')
            with self.assertRaisesRegex(RuntimeError, 'Required asset unavailable'):
                capture.complete_assets()

    def test_coffee_data_requests_the_current_availability_history(self):
        with tempfile.TemporaryDirectory() as temp:
            capture = Capture(temp, 'diyhrt.coffee')
            asked = []

            def fetch(url, headers=None):
                asked.append(url)
                body = b'{"shops": []}' if url.endswith('/api/v1/shops') else b'[]'
                capture.record(url, body, 200, 'application/json')

            with patch.object(capture, 'request', side_effect=fetch):
                capture.coffee_data()
            for window in ('24h', '7d', '30d'):
                self.assertIn(capture.origin + 'api/v1/availability/history?window=' + window, asked)
            self.assertFalse([url for url in asked if 'timeline' in url])

    def test_scroll_retries_after_a_client_side_redirect_destroys_the_page_context(self):
        class RedirectingPage:
            def __init__(self, failures):
                self.failures = failures
                self.scrolls = 0
                self.loads = 0

            def evaluate(self, _script):
                self.scrolls += 1
                if self.scrolls <= self.failures:
                    raise PlaywrightError(
                        'Page.evaluate: Execution context was destroyed, '
                        'most likely because of a navigation'
                    )

            def wait_for_load_state(self, _state):
                self.loads += 1

        page = RedirectingPage(failures=1)
        scroll_page(page)
        self.assertEqual((page.scrolls, page.loads), (2, 1))
        with self.assertRaises(PlaywrightError):
            scroll_page(RedirectingPage(failures=3))

        class BrokenPage(RedirectingPage):
            def evaluate(self, _script):
                raise PlaywrightError('Page.evaluate: Target closed')

        with self.assertRaises(PlaywrightError):
            scroll_page(BrokenPage(failures=0))

    def test_export_contains_pages_api_responses_and_utc_dates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            capture = Capture(root / 'raw', 'diyhrt.coffee')
            capture.record(
                capture.origin,
                b'<html><head><title>Fixture</title></head><body>Archived content</body></html>',
                200,
                'text/html',
                timestamp='2026-10-15T03:00:00-04:00',
            )
            capture.record(
                capture.origin + 'api/v1/me',
                b'{"error":"unauthenticated"}',
                401,
                'application/json',
            )
            capture.export(root / 'output')
            self.assertEqual(capture.pages[capture.origin]['ts'], '2026-10-15T07:00:00Z')
            manifest = json.loads((root / 'output' / 'archive.json').read_text())
            self.assertEqual(len(manifest['responses']), 2)
            self.assertEqual(manifest['responses'][capture.origin + 'api/v1/me']['status'], 401)
            self.assertIn('Archived content', (root / 'output' / 'index.html').read_text())
            self.assertNotIn('replay-web-page', (root / 'output' / 'index.html').read_text())


if __name__ == '__main__':
    unittest.main()
