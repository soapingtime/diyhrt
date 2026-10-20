# SPDX-License-Identifier: GPL-3.0-only

import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup
import requests

from mirror import Assets, mirror, publish_snapshot


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class MirrorTests(unittest.TestCase):
    def test_publish_failure_restores_the_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            destination = root / 'site'
            destination.mkdir()
            (destination / 'index.html').write_text('previous snapshot')
            stage = root / 'new'
            stage.mkdir()
            (stage / 'index.html').write_text('new snapshot')
            rename = Path.rename

            def fail_new(path, target):
                if path == stage:
                    raise OSError('simulated publication failure')
                return rename(path, target)

            with patch.object(Path, 'rename', fail_new):
                with self.assertRaises(OSError):
                    publish_snapshot(stage, destination, root / 'backup')
            self.assertEqual((destination / 'index.html').read_text(), 'previous snapshot')

    @classmethod
    def setUpClass(cls):
        cls.remote = tempfile.TemporaryDirectory()
        cls.web = Path(cls.remote.name)
        for name, data in {
            'app.js': b'window.archived = true;',
            'font.woff2': b'font fixture',
            'image.png': b'image fixture',
            'nested.css': b'.nested { color: red; }',
            'style.css': b'@import "nested.css"; @font-face { src: url("font.woff2"); } .pic { background: url(image.png); }',
        }.items():
            (cls.web / name).write_bytes(data)
        handler = functools.partial(QuietHandler, directory=cls.remote.name)
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = 'http://127.0.0.1:' + str(cls.server.server_port) + '/'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.remote.cleanup()

    def test_assets_are_local_and_nested_css_is_captured(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            page = root / 'index.html'
            page.write_text(
                '''<html><head>
                <link rel="stylesheet" href="REMOTEstyle.css" integrity="old">
                <link rel="preconnect" href="https://example.com">
                <script src="REMOTEapp.js" integrity="old"></script>
                <script src="https://static.cloudflareinsights.com/beacon.min.js"></script>
                </head><body style="background: url(REMOTEimage.png)">
                <img src="REMOTEimage.png" srcset="REMOTEimage.png 1x, REMOTEimage.png 2x">
                <a href="https://example.com/next#heading">next</a>
                <a href="https://elsewhere.test/">external</a>
                </body></html>'''.replace('REMOTE', self.url)
            )
            (root / 'next.html').write_text('<html><head></head><body>next</body></html>')
            Assets(root, 'https://example.com/', wait=0).run()
            soup = BeautifulSoup(page.read_text(), 'html.parser')
            for tag in soup.select('script[src], link[href], img[src]'):
                value = tag.get('src') or tag['href']
                self.assertFalse(urlsplit(value).netloc)
                self.assertTrue((root / unquote(value)).is_file())
            self.assertEqual(soup.a['href'], 'next.html#heading')
            self.assertEqual(soup.find_all('a')[1]['href'], 'https://elsewhere.test/')
            self.assertIsNone(soup.select_one('[integrity]'))
            self.assertIsNotNone(soup.select_one('meta[http-equiv="Content-Security-Policy"]'))
            self.assertEqual(len(list((root / '_assets').iterdir())), 5)
            for css in (root / '_assets').glob('*.css'):
                self.assertNotIn('http://', css.read_text())
            self.assertNotIn('http://', soup.body['style'])
            self.assertNotIn('http://', soup.img['srcset'])

    def test_asset_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            assets = Assets(temp, self.url, wait=0)
            with self.assertRaises(requests.HTTPError):
                assets.asset('missing.js', self.url, Path(temp) / 'index.html')

    def test_query_filenames_are_escaped_for_static_hosting(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            asset = root / 'image.png?v=1'
            asset.write_bytes(b'image')
            assets = Assets(root, 'https://example.com/', wait=0)
            self.assertEqual(
                assets.asset('/image.png?v=1', assets.origin, root / 'index.html'),
                'image.png%3Fv%3D1',
            )

    def test_static_app_preserves_content_and_document_relative_background(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'css').mkdir()
            (root / 'image.png').write_bytes(b'image')
            (root / 'css' / 'app.css').write_text(':root { --background: url(/image.png); }')
            page = root / 'index.html'
            page.write_text('''<html><head><link rel="stylesheet" href="css/app.css">
                <script src="/_next/runtime.js"></script></head>
                <body><h1>Archived content</h1><button>Live action</button>
                <div style="background-image: var(--background)">content</div>
                </body></html>''')
            Assets(root, 'https://example.com/', wait=0, static=True).run()
            soup = BeautifulSoup(page.read_text(), 'html.parser')
            self.assertIsNone(soup.script)
            self.assertTrue(soup.button.has_attr('disabled'))
            self.assertEqual(soup.h1.get_text(), 'Archived content')
            self.assertIn('outdated', soup.select_one('#archive-notice').get_text())
            self.assertEqual(soup.div['style'], 'background-image: url("image.png");')

    def test_unavailable_image_becomes_a_link_instead_of_a_remote_request(self):
        with tempfile.TemporaryDirectory() as temp:
            page = Path(temp) / 'index.html'
            page.write_text(
                '<html><head></head><body><img src="'
                + self.url
                + 'gone.png" alt="Original diagram"></body></html>'
            )
            Assets(temp, 'https://example.com/', wait=0).run()
            soup = BeautifulSoup(page.read_text(), 'html.parser')
            self.assertIsNone(soup.img)
            self.assertEqual(soup.a['href'], self.url + 'gone.png')
            self.assertEqual(soup.a.get_text(), 'Original diagram')

    def test_failed_download_keeps_existing_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'index.html').write_text('previous snapshot')
            with patch('mirror.subprocess.run') as run:
                run.return_value.stdout = 'GNU Wget 1.21.4'
                run.return_value.returncode = 4
                with self.assertRaises(RuntimeError):
                    mirror('example.com', [], '', output=str(root))
            self.assertEqual((root / 'index.html').read_text(), 'previous snapshot')

    def test_seed_fragments_require_visible_content(self):
        cases = [
            ('navigation', '<nav><a href="/">Home</a></nav>', False),
            ('empty', '<!-- navigation -->\n<div> </div>', True),
            ('metadata', '<head><title>Navigation</title></head><script>load()</script>', True),
            ('empty body', '<html><head><title>Navigation</title></head><body> </body></html>', True),
        ]
        for name, fragment, error in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / 'archive'
                root.mkdir()
                previous = root / 'index.html'
                previous.write_text('previous snapshot')

                with patch('mirror.subprocess.run') as run:
                    run.return_value.stdout = 'GNU Wget 1.21.4'
                    run.return_value.returncode = 0

                    def download(command, **kwargs):
                        for argument in command:
                            if argument.startswith('--directory-prefix='):
                                stage = Path(argument.split('=', 1)[1]) / 'example.com'
                                stage.mkdir()
                                (stage / 'index.html').write_text(
                                    '<html><head></head><body>Home</body></html>'
                                )
                                (stage / 'nav.html').write_text(fragment)
                        return run.return_value

                    run.side_effect = download
                    arguments = (
                        'example.com',
                        ['https://example.com/', 'https://example.com/nav.html'],
                        '',
                    )
                    if error:
                        with self.assertRaisesRegex(RuntimeError, 'Expected content missing'):
                            mirror(*arguments, output=str(root))
                        self.assertEqual(previous.read_text(), 'previous snapshot')
                        self.assertEqual(list(root.iterdir()), [previous])
                    else:
                        mirror(*arguments, output=str(root))
                        document = BeautifulSoup((root / 'nav.html').read_text(), 'html.parser')
                        self.assertEqual(document.a.get_text(), 'Home')
                        self.assertEqual(document.a['href'], 'index.html')

    def test_wiki_capture_requires_content_on_every_seed_page(self):
        wiki = '<div class="wiki-page-content"><div class="md">Wiki content</div></div>'
        login = '<h1>Log in to Reddit</h1>'
        empty = '<div class="wiki-page-content"><div class="md"> </div></div>'
        cases = [
            ('blocked', {}, 'Seed page not downloaded'),
            ('partial', {'wiki.html': wiki}, 'Seed page not downloaded'),
            ('login', {'wiki.html': login, 'next.html': wiki}, 'Expected content missing'),
            ('later login', {'wiki.html': wiki, 'next.html': login}, 'Expected content missing'),
            ('empty wiki', {'wiki.html': wiki, 'next.html': empty}, 'Expected content missing'),
            ('complete', {'wiki.html': wiki, 'next.html': wiki}, None),
        ]
        for name, pages, error in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / 'reddit'
                root.mkdir()
                previous = root / 'index.html'
                previous.write_text('previous snapshot')

                with patch('mirror.subprocess.run') as run:
                    run.return_value.stdout = 'GNU Wget 1.21.4'
                    run.return_value.returncode = 8 if error else 0

                    def download(command, **kwargs):
                        for argument in command:
                            if argument.startswith('--directory-prefix='):
                                stage = Path(argument.split('=', 1)[1]) / 'example.com'
                                stage.mkdir()
                                for filename, content in pages.items():
                                    (stage / filename).write_text(
                                        '<html><head></head><body>' + content + '</body></html>'
                                    )
                        return run.return_value

                    run.side_effect = download
                    arguments = (
                        'example.com',
                        ['https://example.com/wiki', 'https://example.com/next'],
                        '',
                    )
                    options = {'output': str(root), 'require_selector': '.wiki-page-content .md'}
                    if error:
                        with self.assertRaisesRegex(RuntimeError, error):
                            mirror(*arguments, **options)
                        self.assertEqual(previous.read_text(), 'previous snapshot')
                        self.assertEqual(list(root.iterdir()), [previous])
                    else:
                        mirror(*arguments, **options)
                        self.assertFalse(previous.exists())
                        for filename in pages:
                            document = BeautifulSoup((root / filename).read_text(), 'html.parser')
                            self.assertEqual(document.select_one('.md').get_text(), 'Wiki content')


if __name__ == '__main__':
    unittest.main()
