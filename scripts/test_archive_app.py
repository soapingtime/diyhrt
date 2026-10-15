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
from unittest.mock import patch
import zipfile

from warcio.archiveiterator import ArchiveIterator

from archive_app import Capture


class AppArchiveTests(unittest.TestCase):
    def test_identical_assets_round_trip_through_warc_revisits(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            capture = Capture(root / 'raw', 'example.com')
            capture.record(capture.origin, b'<html><head></head><body>Fixture</body></html>', 200, 'text/html')
            capture.record(capture.origin + 'a.png', b'identical asset', 200, 'image/png')
            capture.record(capture.origin + 'b.png', b'identical asset', 200, 'image/png')
            capture.package(root / 'output')
            restored = Capture(root / 'restored', 'example.com')
            restored.import_warc(capture.directory / 'snapshot.warc.gz')
            self.assertEqual(len(restored.responses), 3)
            item = restored.responses[capture.origin + 'b.png']
            self.assertEqual((restored.directory / item['file']).read_bytes(), b'identical asset')

    def test_replay_removes_collectors_and_preserves_content(self):
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
                result = subprocess.run([
                    os.environ.get('DIYHRT_WGET', 'wget'), '--mirror', '--page-requisites',
                    '--no-parent', '--warc-file=' + str(root / 'crawl'),
                    '--directory-prefix=' + str(root / 'download'), origin + 'index.html',
                ], capture_output=True, text=True)
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
                200, 'text/css',
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
                200, 'text/html',
            )
            capture.record(capture.origin + 'missing.js', b'not found', 404, 'text/plain')
            with self.assertRaisesRegex(RuntimeError, 'Required asset unavailable'):
                capture.complete_assets()

    def test_wacz_contains_pages_api_responses_and_utc_dates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            capture = Capture(root / 'raw', 'diyhrt.coffee')
            capture.record(
                capture.origin,
                b'<html><head><title>Fixture</title></head><body>Archived content</body></html>',
                200, 'text/html', timestamp='2026-10-15T03:00:00-04:00',
            )
            capture.record(
                capture.origin + 'api/v1/me', b'{"error":"unauthenticated"}',
                401, 'application/json',
            )
            capture.package(root / 'output')
            with zipfile.ZipFile(root / 'output' / 'snapshot.wacz') as archive:
                pages = archive.read('pages/pages.jsonl').decode().splitlines()
                self.assertEqual(json.loads(pages[1])['url'], capture.origin)
                self.assertEqual(json.loads(pages[1])['ts'], '2026-10-15T07:00:00Z')
            with (capture.directory / 'snapshot.warc.gz').open('rb') as stream:
                records = list(ArchiveIterator(stream))
                self.assertEqual(len(records), 2)
                self.assertEqual(records[1].http_headers.get_statuscode(), '401')
            manifest = json.loads((root / 'output' / 'archive.json').read_text())
            self.assertEqual(manifest['responses'], 2)
            self.assertIn('snapshot.wacz?v=', (root / 'output' / 'index.html').read_text())


if __name__ == '__main__':
    unittest.main()
