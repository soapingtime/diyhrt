# SPDX-License-Identifier: GPL-3.0-only

"""Capture interactive sites as WACZ files with a local ReplayWeb.page viewer.

GNU Wget records the crawl and CSS requisites. Chromium records rendered routes,
lazy assets and public API responses. A failed capture leaves the last archive
intact. Captures use a fresh anonymous browser context and only record GETs.
"""

import argparse
from datetime import datetime, timezone
import hashlib
from http import HTTPStatus
import io
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import requests
import tinycss2
from warcio.archiveiterator import ArchiveIterator
from warcio.statusandheaders import StatusAndHeaders
from warcio.warcwriter import WARCWriter

from mirror import USER_AGENT, publish_snapshot


LIVE_SERVICES = {'static.cloudflareinsights.com', 'challenges.cloudflare.com'}


def normalize_url(url):
    parts = urlsplit(url)
    return parts._replace(path=parts.path or '/', fragment='').geturl()


NEXT_REPLAY = """
// CAPTCHA is a live authentication service; never claim verification in replay.
window.turnstile = {
    render: (_element, options) => {
        queueMicrotask(() => options['error-callback']?.());
        return 'archive-service-unavailable';
    },
    reset: () => {},
    remove: () => {},
    getResponse: () => '',
};
(() => {
    const recordedFetch = window.fetch.bind(window);
    window.fetch = (input, options) => {
        const url = typeof input === 'string' ? input : input.url;
        if (url && /[?&]_rsc=/.test(url)) {
            const normalized = url.replace(/([?&]_rsc=)[^&]*/, '$1archive');
            input = typeof input === 'string' ? normalized : new Request(normalized, input);
        }
        return recordedFetch(input, options);
    };
})();
window.addEventListener('click', event => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey ||
        event.ctrlKey || event.shiftKey || event.altKey) return;
    const anchor = event.target.closest && event.target.closest('a[href]');
    if (!anchor || anchor.target === '_blank' || anchor.hasAttribute('download')) return;
    const url = new URL(anchor.href, window.location.href);
    if (url.origin !== window.location.origin || url.hash) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    window.location.assign(url.href);
}, true);
"""

VIEWER = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{host} archive</title>
    <script src="../replay/ui.js"></script>
    <style>
        html, body {{ height: 100%; margin: 0; }}
        body {{ display: flex; flex-direction: column; }}
        p {{ margin: 0; padding: 8px; font: 16px sans-serif; }}
        #archive {{ display: flex; flex: 1; min-height: 0; }}
        replay-web-page {{ display: block; flex: 1; min-height: 0; }}
    </style>
</head>
<body>
    <p>Archived {date}. <a href="snapshot.wacz">Download archive</a> ·
       <a href="https://{host}/" target="_blank" rel="noopener noreferrer">Original site</a> ·
       <a href="../index.html">All sites</a></p>
    <div id="archive"></div>
    <script>
        (async () => {{
            const source = 'snapshot.wacz?v={digest}';
            const viewer = document.createElement('replay-web-page');
            viewer.setAttribute('source', source);
            viewer.setAttribute('url', 'https://{host}/');
            viewer.setAttribute('replayBase', '../replay/');
            viewer.setAttribute('deepLink', '');
            const response = await fetch(source, {{ method: 'HEAD' }});
            if (response.headers.get('Accept-Ranges') !== 'bytes') {{
                viewer.setAttribute('loading', 'eager');
            }}
            document.getElementById('archive').append(viewer);
        }})().catch(() => {{
            document.getElementById('archive').textContent =
                'Serve this folder with python -m http.server and open http://localhost:8000.';
        }});
    </script>
    <noscript>Use ReplayWeb.page to open the downloaded archive.</noscript>
</body>
</html>
"""


class Capture:
    def __init__(self, directory, host):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.host = host
        self.allowed_hosts = {host}
        if host == 'diyhrt.coffee':
            self.allowed_hosts.add('forum.diyhrt.coffee')
        self.origin = 'https://' + host + '/'
        self.responses = {}
        self.pages = {}
        self.session = requests.Session()
        self.session.headers['User-Agent'] = USER_AGENT

    def document(self, body, replay=False):
        soup = BeautifulSoup(body, 'html.parser')
        for tag in list(soup.find_all('script')):
            text = tag.get_text()
            collector = urlsplit(urljoin(self.origin, tag.get('src', ''))).hostname in LIVE_SERVICES
            fingerprint = '__CF$cv$params' in text and 'challenge-platform' in text
            previous_shim = tag.get('id') == 'archive-next-replay' or 'const recordedFetch = window.fetch.bind(window);' in text
            if collector or fingerprint or previous_shim:
                tag.decompose()
        if self.host == 'valerie.vg':
            for tag in soup.select('[data-bs-toggle="tooltip"]'):
                if tag.get('data-bs-title') in ('', 'null'):
                    tag.attrs.pop('data-bs-toggle', None)
            for tag in soup.find_all('img'):
                if tag.get('src') == '' and not tag.get('srcset'):
                    if tag.get('alt'):
                        label = soup.new_tag('span')
                        label.string = tag['alt']
                        tag.replace_with(label)
                    else:
                        tag.decompose()
        if replay and self.host == 'diyhrt.coffee' and soup.head:
            script = soup.new_tag('script', id='archive-next-replay')
            script.string = NEXT_REPLAY
            soup.head.insert(0, script)
        return str(soup).encode('utf-8')

    def record(self, url, body, status, content_type, location=None, timestamp=None):
        url = normalize_url(url)
        if urlsplit(url).hostname in LIVE_SERVICES:
            return
        digest = hashlib.sha256(body).hexdigest()
        filename = digest + '.body'
        if not (self.directory / filename).exists():
            (self.directory / filename).write_bytes(body)
        if timestamp:
            instant = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        else:
            instant = datetime.now(timezone.utc)
        timestamp = instant.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        self.responses[url] = {
            'file': filename, 'status': int(status), 'content_type': content_type,
            'location': location, 'timestamp': timestamp,
        }
        if (status == 200 and content_type.startswith('text/html') and
                urlsplit(url).hostname in self.allowed_hosts and
                not re.search(r'[?&]_rsc=', url)):
            soup = BeautifulSoup(body, 'html.parser')
            title = soup.title.get_text() if soup.title else url
            if title.strip().lower() in ('just a moment...', 'attention required! | cloudflare'):
                raise RuntimeError('An anti-bot page is not a site snapshot: ' + url)
            self.pages[url] = {'url': url, 'title': title, 'ts': timestamp}

    def request(self, url, headers=None):
        url = normalize_url(url)
        if url in self.responses:
            return
        time.sleep(1)
        response = self.session.get(url, headers=headers, timeout=60, allow_redirects=False)
        self.record(
            url, response.content, response.status_code,
            response.headers.get('Content-Type', 'application/octet-stream'),
            response.headers.get('Location'),
        )
        print('record:', response.status_code, url, flush=True)
        if response.is_redirect:
            target = urljoin(url, response.headers['Location'])
            if urlsplit(target).hostname in self.allowed_hosts:
                self.request(target)

    def import_warc(self, path):
        payloads = {}
        with Path(path).open('rb') as stream:
            for record in ArchiveIterator(stream):
                if record.rec_type not in ('response', 'revisit') or not record.http_headers:
                    continue
                digest = record.rec_headers.get_header('WARC-Payload-Digest')
                if record.rec_type == 'revisit':
                    if digest not in payloads:
                        raise RuntimeError('Unresolved WARC revisit: ' + str(digest))
                    body = payloads[digest].read_bytes()
                else:
                    body = record.content_stream().read()
                url = normalize_url(record.rec_headers.get_header('WARC-Target-URI'))
                self.record(
                    url, body,
                    int(record.http_headers.get_statuscode()),
                    record.http_headers.get_header('Content-Type', 'application/octet-stream'),
                    record.http_headers.get_header('Location'),
                    record.rec_headers.get_header('WARC-Date'),
                )
                if digest and url in self.responses:
                    payloads[digest] = self.directory / self.responses[url]['file']

    def browser(self, executable=None, seeds=None):
        pending = list(seeds) if seeds is not None else [self.origin] + list(self.pages)
        if seeds is None and self.host == 'diyhrt.coffee':
            pending.append('https://forum.diyhrt.coffee/')
        visited = set()
        failures = []
        with sync_playwright() as playwright:
            options = {'headless': True}
            if executable:
                options['executable_path'] = executable
            browser = playwright.chromium.launch(**options)
            context = browser.new_context(viewport={'width': 1280, 'height': 900})
            page = context.new_page()
            active = set()

            def serve_cached(route):
                request = route.request
                if request.method != 'GET' or urlsplit(request.url).hostname in LIVE_SERVICES:
                    route.abort()
                    return
                cached = self.responses.get(request.url)
                if cached:
                    headers = {'Content-Type': cached['content_type']}
                    if cached['location']:
                        headers['Location'] = cached['location']
                    body = (self.directory / cached['file']).read_bytes()
                    if cached['content_type'].startswith('text/html'):
                        body = self.document(body)
                    route.fulfill(
                        status=cached['status'], headers=headers,
                        body=body,
                    )
                else:
                    route.continue_()

            def started(request):
                if request.resource_type != 'eventsource':
                    active.add(request)

            page.route('**/*', serve_cached)
            page.on('request', started)
            page.on('requestfinished', lambda request: active.discard(request))
            page.on('requestfailed', lambda request: active.discard(request))

            def response_received(response):
                if response.request.method != 'GET':
                    return
                kind = response.headers.get('content-type', 'application/octet-stream')
                if 'text/event-stream' in kind:
                    return
                try:
                    body = response.body() if response.status not in (301, 302, 303, 307, 308) else b''
                except Exception as error:
                    failures.append((response.url, str(error)))
                    return
                self.record(
                    response.url, body, response.status, kind,
                    response.headers.get('location'),
                    self.responses.get(response.url, {}).get('timestamp'),
                )

            page.on('response', response_received)
            while pending:
                url = pending.pop(0)
                if url in visited or urlsplit(url).hostname not in self.allowed_hosts:
                    continue
                visited.add(url)
                previous = self.responses.get(url)
                if previous and previous['location']:
                    target = urljoin(url, previous['location'])
                    if urlsplit(target).hostname not in self.allowed_hosts:
                        continue
                print('page:', url, flush=True)
                time.sleep(1)
                response = page.goto(url, wait_until='load', timeout=60000)
                if response and response.status >= 400 and url in self.pages:
                    raise RuntimeError('A previously captured page failed: ' + url)
                page.evaluate('''async () => {
                    for (let y = 0; y < document.body.scrollHeight; y += 700) {
                        window.scrollTo(0, y);
                        await new Promise(resolve => setTimeout(resolve, 40));
                    }
                }''')
                deadline = time.monotonic() + 60
                while True:
                    page.wait_for_timeout(300)
                    if not active:
                        break
                    if time.monotonic() > deadline:
                        raise RuntimeError('Page requests did not finish: ' + url)
                for href in page.locator('a[href]').evaluate_all('(links) => links.map(a => a.href)'):
                    parts = urlsplit(href)
                    target = normalize_url(href)
                    if parts.hostname not in self.allowed_hosts or re.search(r'/(logout|auth|admin)(/|$)', parts.path):
                        continue
                    if target not in visited and target not in pending:
                        if not Path(parts.path).suffix or parts.path.endswith(('.html', '.htm')):
                            pending.append(target)
            browser.close()
        # A response canceled by a later navigation is still recoverable as a GET.
        for url, _ in failures:
            if url not in self.responses:
                headers = {'RSC': '1'} if re.search(r'[?&]_rsc=', url) else None
                self.request(url, headers=headers)

    def coffee_data(self):
        endpoints = [
            'shops', 'items', 'stock/current', 'stock/changes',
            'stock/changes?limit=30', 'stock/changes?limit=50',
            'stats', 'uptime', 'availability', 'announcement', 'whats-new', 'me',
            'discord/bot-invite',
            'availability/timeline?window=24h', 'availability/timeline?window=7d',
            'availability/timeline?window=30d', 'feed/stock.rss?only=restocks',
        ]
        for endpoint in endpoints:
            url = urljoin(self.origin, 'api/v1/' + endpoint)
            self.request(url)
            if endpoint not in ('me', 'discord/bot-invite') and self.responses[url]['status'] != 200:
                raise RuntimeError('Public data unavailable: ' + url)
        self.request(urljoin(self.origin, 'api/forum/me/account'))
        shops_record = self.responses[urljoin(self.origin, 'api/v1/shops')]
        shops = json.loads((self.directory / shops_record['file']).read_bytes())
        if isinstance(shops, dict):
            shops = shops.get('shops', shops.get('data', []))
        for shop in shops:
            self.request(urljoin(self.origin, 'api/v1/vendors/' + str(shop['id']) + '/reviews'))
        for record in list(self.responses.values()):
            if 'json' not in record['content_type']:
                continue
            text = (self.directory / record['file']).read_text()
            for image in re.findall(r'[0-9a-f]{64}\.(?:png|jpe?g|webp)', text):
                self.request(urljoin(self.origin, 'api/v1/reviews/images/' + image))
        for theme in ('midnight', 'summer', 'turquoise', 'crimson', 'sakura', 'green', 'paper'):
            self.request(urljoin(self.origin, 'mascot/' + theme + '.png'))
            for character in '0123456789.':
                name = 'dot' if character == '.' else character
                self.request(urljoin(self.origin, 'counter/' + theme + '/' + name + '.png'))
        self.request(urljoin(self.origin, 'mc-pickaxe.png'))
        for url in list(self.pages):
            separator = '&' if '?' in url else '?'
            self.request(url + separator + '_rsc=archive', headers={'RSC': '1'})

    def complete_assets(self):
        def css_urls(text):
            def walk(tokens):
                importing = False
                for token in tokens:
                    if token.type == 'at-keyword' and token.value.lower() == 'import':
                        importing = True
                    elif token.type == 'literal' and token.value == ';':
                        importing = False
                    if token.type == 'url':
                        yield token.value
                    elif token.type == 'string' and importing:
                        yield token.value
                    elif token.type == 'function' and token.lower_name == 'url':
                        for argument in token.arguments:
                            if argument.type == 'string':
                                yield argument.value
                    for attribute in ('content', 'arguments'):
                        children = getattr(token, attribute, None)
                        if children:
                            yield from walk(children)

            yield from walk(tinycss2.parse_component_value_list(text))

        checked = set()
        while True:
            pending = [url for url in self.responses if url not in checked]
            if not pending:
                break
            for url in pending:
                checked.add(url)
                record = self.responses[url]
                if record['status'] != 200:
                    continue
                kind = record['content_type']
                urls = []
                if kind.startswith(('text/html', 'text/css')):
                    text = (self.directory / record['file']).read_text()
                    if kind.startswith('text/css'):
                        urls.extend(css_urls(text))
                    else:
                        soup = BeautifulSoup(text, 'html.parser')
                        for tag in soup.select('[src], video[poster], object[data]'):
                            for attribute in ('src', 'poster', 'data'):
                                if tag.get(attribute):
                                    urls.append(tag[attribute])
                        for tag in soup.select('[srcset]'):
                            if 'data:' not in tag['srcset']:
                                urls.extend(item.split()[0] for item in tag['srcset'].split(',') if item.split())
                        for tag in soup.select('link[href]'):
                            rel = set(tag.get('rel', []))
                            if rel & {'stylesheet', 'icon', 'apple-touch-icon', 'mask-icon',
                                      'manifest', 'preload', 'modulepreload'}:
                                urls.append(tag['href'])
                        for tag in soup.select('a[href]'):
                            target = urljoin(url, tag['href'])
                            if urlsplit(target).hostname in self.allowed_hosts:
                                if not re.search(r'/(logout|auth|admin)(/|$)', urlsplit(target).path):
                                    self.request(urlsplit(target)._replace(fragment='').geturl())
                        for tag in soup.select('meta[content]'):
                            name = tag.get('property') or tag.get('name')
                            if name in ('og:image', 'twitter:image'):
                                urls.append(tag['content'])
                        for tag in soup.select('[style]'):
                            urls.extend(css_urls(tag['style']))
                        for tag in soup.find_all('style'):
                            urls.extend(css_urls(tag.get_text()))
                elif 'manifest' in kind or urlsplit(url).path.endswith('.webmanifest'):
                    manifest = json.loads((self.directory / record['file']).read_bytes())
                    for entry in manifest.get('icons', []) + manifest.get('screenshots', []):
                        if entry.get('src'):
                            urls.append(entry['src'])
                for value in urls:
                    if not value or value.startswith(('#', 'data:', 'blob:')):
                        continue
                    target = normalize_url(urljoin(url, value))
                    if urlsplit(target).hostname in LIVE_SERVICES:
                        continue
                    if urlsplit(target).scheme not in ('http', 'https'):
                        continue
                    self.request(target)
                    asset = self.responses[target]
                    if asset['location']:
                        location = urljoin(target, asset['location'])
                        self.request(location)
                        asset = self.responses[location]
                    if asset['status'] != 200:
                        raise RuntimeError('Required asset unavailable: ' + target)

    def package(self, destination):
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        warc = self.directory / 'snapshot.warc.gz'
        pages = self.directory / 'pages.jsonl'
        with warc.open('wb') as stream:
            writer = WARCWriter(stream, gzip=True)
            payloads = {}
            for url, item in sorted(self.responses.items()):
                body = (self.directory / item['file']).read_bytes()
                if item['content_type'].startswith('text/html') and item['status'] == 200:
                    body = self.document(body, replay=True)
                headers = [('Content-Type', item['content_type']), ('Content-Length', str(len(body)))]
                if item['location']:
                    headers.append(('Location', item['location']))
                status = str(item['status']) + ' ' + HTTPStatus(item['status']).phrase
                http = StatusAndHeaders(status, headers, protocol='HTTP/1.1')
                key = hashlib.sha256(body).hexdigest()
                if item['status'] == 200 and body and key in payloads:
                    previous = payloads[key]
                    record = writer.create_revisit_record(
                        url, previous['digest'], previous['url'], previous['timestamp'],
                        http_headers=http,
                    )
                    record.rec_headers.replace_header('WARC-Date', item['timestamp'])
                    writer.write_record(record)
                    continue
                record = writer.create_warc_record(
                    url, 'response', payload=io.BytesIO(body), http_headers=http,
                    warc_headers_dict={'WARC-Date': item['timestamp']},
                )
                writer.write_record(record)
                if item['status'] == 200 and body:
                    payloads[key] = {
                        'url': url, 'timestamp': item['timestamp'],
                        'digest': record.rec_headers.get_header('WARC-Payload-Digest'),
                    }
        with pages.open('w') as stream:
            stream.write(json.dumps({'format': 'json-pages-1.0', 'id': 'pages', 'title': self.host}) + '\n')
            for page in sorted(self.pages.values(), key=lambda item: item['url']):
                stream.write(json.dumps(page) + '\n')
        archive = destination / 'snapshot.wacz'
        subprocess.run([
            'wacz', 'create', str(warc), '--pages', str(pages), '--copy-pages',
            '--title', self.host, '--url', self.origin, '-o', str(archive),
        ], check=True)
        subprocess.run(['wacz', 'validate', '-f', str(archive)], check=True)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        date = datetime.now(timezone.utc).date().isoformat()
        (destination / 'index.html').write_text(VIEWER.format(host=self.host, date=date, digest=digest))
        manifest = {
            'source': self.origin, 'captured': date, 'sha256': digest,
            'hosts': sorted(self.allowed_hosts),
            'pages': sorted(self.pages), 'responses': len(self.responses),
        }
        (destination / 'archive.json').write_text(json.dumps(manifest, indent=2) + '\n')


def archive(host, wget, executable, reject):
    if not host or '/' in host or host.startswith('.'):
        raise ValueError('Expected a hostname')
    help_text = subprocess.check_output([wget, '--help'], text=True)
    if '--warc-file' not in help_text:
        raise RuntimeError('Interactive archives require GNU Wget with WARC support')
    destination = Path(host)
    with tempfile.TemporaryDirectory(prefix='.diyhrt-app-', dir=destination.parent) as temp:
        root = Path(temp)
        raw = root / 'crawl'
        seeds = ['https://' + host + '/']
        if host == 'valerie.vg':
            seeds.append('https://valerie.vg/meds/products/')
        if host == 'diyhrt.coffee':
            seeds.append('https://forum.diyhrt.coffee/')
        command = [
            wget, '--mirror', '--page-requisites', '--no-parent',
            '--adjust-extension', '--wait=1', '--random-wait', '--limit-rate=10m',
            '--timeout=60', '--tries=3', '--user-agent=' + USER_AGENT,
            '--directory-prefix=' + str(root / 'downloads'), '--warc-file=' + str(raw),
        ]
        if reject:
            command.append('--reject-regex=' + reject)
        result = subprocess.run(command + seeds, check=False)
        if result.returncode not in (0, 8):
            raise RuntimeError('wget failed: ' + str(result.returncode))
        capture = Capture(root / 'responses', host)
        capture.import_warc(str(raw) + '.warc.gz')
        if capture.origin not in capture.pages:
            raise RuntimeError('No homepage captured; keeping the previous snapshot')
        capture.browser(executable)
        if host == 'diyhrt.coffee':
            capture.coffee_data()
        capture.complete_assets()
        staged = root / 'finished'
        capture.package(staged)
        backup = root / 'previous'
        publish_snapshot(staged, destination, backup)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host')
    parser.add_argument('--wget', default='wget')
    parser.add_argument('--chromium')
    parser.add_argument('--reject', default=r'/(auth|logout|admin)(/|$)')
    args = parser.parse_args()
    archive(args.host, args.wget, args.chromium, args.reject)


if __name__ == '__main__':
    main()
