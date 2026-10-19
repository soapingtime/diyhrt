# SPDX-License-Identifier: GPL-3.0-only

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from bs4 import BeautifulSoup

from archive_app import Capture
from export_app import Export


class ExportTests(unittest.TestCase):
    def test_javascript_failure_reports_the_parser_error(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            capture = Capture(root / 'raw', 'example.com')
            capture.record(
                capture.origin,
                b"<html><head></head><body><script>window.value = 'unfinished</script></body></html>",
                200,
                'text/html',
            )
            with self.assertRaisesRegex(
                RuntimeError, r'JavaScript relocation failed:[\s\S]*Unterminated string constant'
            ):
                capture.export(root / 'output')

    def test_flight_keeps_utf8_text_lengths_and_relocates_split_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capture = Capture(root / 'raw', 'example.com')
            text = '🌸 keep /tools and "quoted" text unchanged'
            flight = '2:T' + format(len(text.encode()), 'x') + ',' + text
            flight += (
                '0:'
                + json.dumps(
                    {
                        'c': ['', ''],
                        'href': '/tools',
                        'style': {'backgroundImage': 'url("/image.svg")'},
                    }
                )
                + '\n'
            )
            split = flight.index('/tools', len('2:T')) + 3
            chunks = [flight[:split], flight[split:]]
            scripts = ''.join(
                '<script>self.__next_f.push([1,' + json.dumps(chunk) + '])</script>'
                for chunk in chunks
            )
            capture.record(
                capture.origin,
                (
                    '<html><head></head><body>Home'
                    + scripts
                    + '<div id=tail>Saved tail</div></body></html>'
                ).encode(),
                200,
                'text/html',
            )
            capture.record(
                capture.origin + 'tools',
                b'<html><head></head><body>Tools</body></html>',
                200,
                'text/html',
            )
            capture.record(capture.origin + 'image.svg', b'<svg/>', 200, 'image/svg+xml')
            Export(capture).write(root / 'site')
            soup = BeautifulSoup((root / 'site/index.html').read_text(), 'html.parser')
            inline = [
                script.string
                for script in soup.find_all('script')
                if script.string and '__next_f.push' in script.string
            ]
            self.assertEqual(soup.body.find_all(recursive=False)[-1].name, 'script')
            self.assertIsNotNone(soup.select_one('#tail'))
            javascript = """
const vm = require('node:vm');
const context = {self: {__next_f: []}};
for (const source of JSON.parse(require('node:fs').readFileSync(0, 'utf8'))) {
    vm.runInNewContext(source, context);
}
process.stdout.write(context.self.__next_f.map(item => item[1]).join(''));
"""
            stream = subprocess.check_output(
                ['node', '-e', javascript], input=json.dumps(inline), text=True
            )
            comma = stream.index(',')
            size = int(stream[3:comma], 16)
            data = stream.encode()
            offset = len(stream[: comma + 1].encode())
            self.assertEqual(data[offset : offset + size].decode(), text)
            model = json.loads(data[offset + size :].decode()[2:])
            self.assertEqual(model['href'], '/example.com/tools/')
            self.assertEqual(model['c'], ['', 'example.com', ''])
            self.assertEqual(model['style']['backgroundImage'], 'url("/example.com/image.svg")')

    def test_requisites_redirects_and_duplicate_assets_remain_local(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capture = Capture(root / 'raw', 'diyhrt.coffee')
            source = b'''<html><head><link rel="stylesheet" href="/style.css">
                <script src="https://cdn.example.com/adapter.js"></script></head>
                <body><img src="/image.png">Original content</body></html>'''
            capture.record(capture.origin, source, 200, 'text/html')
            capture.record(
                capture.origin + 'style.css', b'@font-face {src:url(/font.woff2)}', 200, 'text/css'
            )
            capture.record(capture.origin + 'font.woff2', b'font', 200, 'font/woff2')
            capture.record(capture.origin + 'image.png', b'image', 200, 'image/png')
            capture.record('https://forum.diyhrt.coffee/image.png', b'image', 200, 'image/png')
            capture.record(
                'https://cdn.example.com/adapter.js',
                b'',
                302,
                'text/html',
                'https://cdn.example.com/v1.js',
            )
            capture.record(
                'https://cdn.example.com/v1.js',
                b'window.adapter = true;',
                200,
                'application/javascript',
            )
            exported = Export(capture)
            manifest = exported.write(root / 'site')
            html = (root / 'site/index.html').read_text()
            self.assertIn('Original content', html)
            self.assertIn('url("/diyhrt.coffee/font.woff2")', (root / 'site/style.css').read_text())
            self.assertNotIn('src="https://cdn.example.com', html)
            redirect = manifest['responses']['https://cdn.example.com/adapter.js']
            target = manifest['responses']['https://cdn.example.com/v1.js']
            self.assertEqual(redirect['path'], target['path'])
            self.assertEqual(
                exported.records[capture.origin + 'image.png']['file'],
                exported.records['https://forum.diyhrt.coffee/image.png']['file'],
            )
            record = capture.responses[capture.origin]
            self.assertEqual((capture.directory / record['file']).read_bytes(), source)

    def test_query_pages_keep_original_search_and_source_pathname(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capture = Capture(root / 'raw', 'diyhrt.coffee')
            url = 'https://forum.diyhrt.coffee/login?next=%2Fmessages'
            capture.record(url, b'<html><head></head><body>Log in</body></html>', 200, 'text/html')
            manifest = Export(capture).write(root / 'site')
            local = manifest['pages'][url]
            self.assertTrue(local.endswith('?next=%2Fmessages'))
            self.assertTrue(
                (root / 'site' / local.split('?', 1)[0].removeprefix('/diyhrt.coffee/')).is_file()
            )

    def test_catalog_groups_match_punctuation_in_source_labels(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capture = Capture(root / 'raw', 'valerie.vg')
            product = '/meds/products/minoxidil-2'
            catalog = b"""<html><head></head><body>
                <select id="id_product__drug_group"><option value="13">Minoxidil 2%</option></select>
                <a class="list-group-item" href="/meds/products/minoxidil-2">Minoxidil 2%</a>
                </body></html>"""
            group = (
                '<html><head></head><body><a href="' + product + '">Product</a></body></html>'
            ).encode()
            capture.record(capture.origin + 'meds/products/', catalog, 200, 'text/html')
            capture.record(capture.origin + 'meds/groups/minoxidil-2', group, 200, 'text/html')
            Export(capture).write(root / 'site')
            soup = BeautifulSoup(
                (root / 'site/meds/products/index.html').read_bytes(), 'html.parser'
            )
            self.assertEqual(soup.select_one('[data-mirror-search]')['data-mirror-groups'], '13')

    def test_next_pathname_uses_source_routes_without_changing_route_constants(self):
        source = r"""
(() => {
    const hooks = {get usePathname() {return path}};
    const context = {PathnameContext: '/diyhrt.coffee/calculator/'};
    function path() {return context.PathnameContext}
    window.result = [hooks.usePathname(), '/calculator', /\/_next\//.source, '/coins/'.concat('btc.svg')];
})();
"""
        payload = {
            'mapping': {
                'https://diyhrt.coffee/calculator': {
                    'type': 'text/html',
                    'path': '/diyhrt.coffee/calculator/',
                },
                'https://diyhrt.coffee/coins/btc.svg': {
                    'type': 'image/svg+xml',
                    'path': '/diyhrt.coffee/coins/btc.svg',
                },
            },
            'origins': {'https://diyhrt.coffee': '/diyhrt.coffee/'},
            'items': [{'source': source, 'origin': 'https://diyhrt.coffee/', 'canonical': None}],
        }
        script = Path(__file__).with_name('relocate_js.cjs')
        result = subprocess.check_output(
            ['node', str(script)], input=json.dumps(payload), text=True
        )
        rewritten = json.loads(result)[0]
        javascript = (
            "const window = {__mirror: {pathname: () => '/calculator'}};"
            + rewritten
            + '\nprocess.stdout.write(JSON.stringify(window.result));'
        )
        actual = json.loads(subprocess.check_output(['node', '-e', javascript], text=True))
        self.assertEqual(
            actual, ['/calculator', '/calculator', r'\/_next\/', '/diyhrt.coffee/coins/btc.svg']
        )

    def test_saved_react_data_uses_client_rendering_without_hydration(self):
        source = 'window.result = (0, renderer.hydrateRoot)(document, "saved tree", {test: true});'
        payload = {
            'mapping': {},
            'origins': {},
            'items': [{'source': source, 'origin': 'https://example.com/', 'canonical': None}],
        }
        script = Path(__file__).with_name('relocate_js.cjs')
        result = subprocess.check_output(
            ['node', str(script)], input=json.dumps(payload), text=True
        )
        rewritten = json.loads(result)[0]
        javascript = (
            """
const renderer = {hydrateRoot() {throw new Error('Hydration must not run')}};
const document = {};
const window = {__mirror: {mount: (...args) => args}};
"""
            + rewritten
            + '\nprocess.stdout.write(JSON.stringify(window.result.slice(1)));'
        )
        actual = json.loads(subprocess.check_output(['node', '-e', javascript], text=True))
        self.assertEqual(actual, [{}, 'saved tree', {'test': True}])

    def test_public_response_status_and_rsc_cache_keys_survive_local_fetch(self):
        runtime = Path(__file__).with_name('local_app.js').read_text()
        javascript = """
const assert = require('node:assert/strict');
const vm = require('node:vm');
const requests = [];
const responses = {
    '/diyhrt.coffee/_data/me.json': '{"user":null}',
    '/diyhrt.coffee/_data/route.txt': '0:{"saved":true}\\n',
};
const window = {
    __mirror: {
        original: 'https://diyhrt.coffee/', root: '/diyhrt.coffee/',
        origins: {'https://diyhrt.coffee': '/diyhrt.coffee/'},
        records: {
            'https://diyhrt.coffee/api/v1/me': {path:'/diyhrt.coffee/_data/me.json',status:401,type:'application/json'},
            'https://forum.diyhrt.coffee/login?next=%2Fmessages': {path:'/diyhrt.coffee/forum/_pages/login.html?next=%2Fmessages',status:200,type:'text/html'},
            'https://forum.diyhrt.coffee/messages': {path:'/diyhrt.coffee/forum/_pages/login.html?next=%2Fmessages',status:307,type:'text/html',location:'/login?next=%2Fmessages'},
            'https://diyhrt.coffee/?_rsc=archive': {path:'/diyhrt.coffee/_data/route.txt',status:200,type:'text/x-component'},
        },
    },
    fetch: async path => {requests.push(path); return new Response(responses[path]);},
    addEventListener() {},
};
class Element {setAttribute() {}}
class XMLHttpRequest {open() {}}
const context = {window, Element, XMLHttpRequest, URL, Response, Request, Map, EventTarget, DOMException, queueMicrotask,
    document: {readyState: 'complete'},
    location: {href:'https://mirror.example/diyhrt.coffee/', origin:'https://mirror.example'}, console};
for (const type of ['HTMLImageElement','HTMLScriptElement','HTMLLinkElement','HTMLAnchorElement','HTMLSourceElement','HTMLVideoElement']) context[type] = Element;
vm.runInNewContext(RUNTIME, context);
(async () => {
    assert.equal(window.__mirror.pathname('/diyhrt.coffee/forum/_pages/login.html'), '/login');
    const mounted = [];
    const root = {render: value => mounted.push(value)};
    const renderer = {createRoot: () => root};
    assert.equal(window.__mirror.mount(renderer, {}, 'saved tree', {}), root);
    assert.deepEqual(mounted, ['saved tree']);
    context.document.readyState = 'loading';
    let ready;
    context.document.addEventListener = (_name, callback) => {ready = callback;};
    window.__mirror.mount(renderer, {}, 'after parsing', {});
    assert.deepEqual(mounted, ['saved tree']);
    ready();
    assert.deepEqual(mounted, ['saved tree', 'after parsing']);
    const me = await window.fetch('/api/v1/me');
    assert.equal(me.status, 401);
    assert.deepEqual(await me.json(), {user:null});
    const route = await window.fetch('/diyhrt.coffee?_rsc=random');
    assert.equal(route.headers.get('Content-Type'), 'text/x-component');
    assert.match(await route.text(), /saved/);
    const action = await window.fetch('/api/v1/reviews', {method:'POST'});
    assert.equal(action.status, 503);
    assert.deepEqual(requests, ['/diyhrt.coffee/_data/me.json','/diyhrt.coffee/_data/route.txt']);
})().catch(error => {console.error(error); process.exitCode = 1;});
""".replace('RUNTIME', json.dumps(runtime))
        subprocess.run(['node', '-e', javascript], check=True)


if __name__ == '__main__':
    unittest.main()
