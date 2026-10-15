# SPDX-License-Identifier: GPL-3.0-only

"""Capture interactive sites as local pages, assets and public API responses.

GNU Wget records the crawl and CSS requisites. Chromium records rendered routes,
lazy assets and public API responses. A failed capture leaves the last archive
intact. Captures use a fresh anonymous browser context and only record GETs.
"""

import argparse
from datetime import datetime, timezone
import hashlib
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

from mirror import USER_AGENT, publish_snapshot
from export_app import Export
from validate_app import validate


LIVE_SERVICES = {'static.cloudflareinsights.com', 'challenges.cloudflare.com'}


def normalize_url(url):
    parts = urlsplit(url)
    return parts._replace(path=parts.path or '/', fragment='').geturl()


def is_capture_request(request):
    # Next prefetches are saved sequentially by coffee_data() after the page crawl.
    return (
        request.method == 'GET'
        and urlsplit(request.url).hostname not in LIVE_SERVICES
        and request.resource_type != 'eventsource'
        and not re.search(r'[?&]_rsc(?:=|&|$)', request.url)
    )


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

    def document(self, body):
        soup = BeautifulSoup(body, 'html.parser')
        for tag in list(soup.find_all('script')):
            text = tag.get_text()
            collector = urlsplit(urljoin(self.origin, tag.get('src', ''))).hostname in LIVE_SERVICES
            fingerprint = '__CF$cv$params' in text and 'challenge-platform' in text
            tracker = 'matomo' in text and '_paq' in text
            previous_shim = (
                tag.get('id') == 'archive-next-replay'
                or 'const recordedFetch = window.fetch.bind(window);' in text
            )
            if collector or fingerprint or tracker or previous_shim:
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
            'file': filename,
            'status': int(status),
            'content_type': content_type,
            'location': location,
            'timestamp': timestamp,
        }
        if (
            status == 200
            and content_type.startswith('text/html')
            and urlsplit(url).hostname in self.allowed_hosts
            and not re.search(r'[?&]_rsc=', url)
        ):
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
            url,
            response.content,
            response.status_code,
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
                    url,
                    body,
                    int(record.http_headers.get_statuscode()),
                    record.http_headers.get_header('Content-Type', 'application/octet-stream'),
                    record.http_headers.get_header('Location'),
                    record.rec_headers.get_header('WARC-Date'),
                )
                if digest and url in self.responses:
                    payloads[digest] = self.directory / self.responses[url]['file']

    def browser_response(self, url):
        parts = urlsplit(url)
        if parts.hostname in self.allowed_hosts and parts.path.startswith('/api/'):
            # Some anonymous API requests hang in Chromium; use the finite HTTP capture path.
            self.request(url)
        return self.responses.get(normalize_url(url))

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
                if not is_capture_request(request):
                    route.abort()
                    return
                cached = self.browser_response(request.url)
                if cached:
                    headers = {'Content-Type': cached['content_type']}
                    if cached['location']:
                        headers['Location'] = cached['location']
                    body = (self.directory / cached['file']).read_bytes()
                    if cached['content_type'].startswith('text/html'):
                        body = self.document(body)
                    route.fulfill(
                        status=cached['status'],
                        headers=headers,
                        body=body,
                    )
                else:
                    route.continue_()

            def started(request):
                if is_capture_request(request):
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
                    active.discard(response.request)
                    return
                try:
                    body = (
                        response.body() if response.status not in (301, 302, 303, 307, 308) else b''
                    )
                except Exception as error:
                    failures.append((response.url, str(error)))
                    return
                self.record(
                    response.url,
                    body,
                    response.status,
                    kind,
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
                        pending_urls = ', '.join(sorted(request.url for request in active))
                        raise RuntimeError(
                            'Page requests did not finish: ' + url + ': ' + pending_urls
                        )
                for href in page.locator('a[href]').evaluate_all(
                    '(links) => links.map(a => a.href)'
                ):
                    parts = urlsplit(href)
                    target = normalize_url(href)
                    if parts.hostname not in self.allowed_hosts or re.search(
                        r'/(logout|auth|admin)(/|$)', parts.path
                    ):
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
            'shops',
            'items',
            'stock/current',
            'stock/changes',
            'stock/changes?limit=30',
            'stock/changes?limit=50',
            'stats',
            'uptime',
            'availability',
            'announcement',
            'whats-new',
            'me',
            'discord/bot-invite',
            'availability/timeline?window=24h',
            'availability/timeline?window=7d',
            'availability/timeline?window=30d',
            'feed/stock.rss?only=restocks',
        ]
        for endpoint in endpoints:
            url = urljoin(self.origin, 'api/v1/' + endpoint)
            self.request(url)
            if (
                endpoint not in ('me', 'discord/bot-invite')
                and self.responses[url]['status'] != 200
            ):
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
                                urls.extend(
                                    item.split()[0]
                                    for item in tag['srcset'].split(',')
                                    if item.split()
                                )
                        for tag in soup.select('link[href]'):
                            rel = set(tag.get('rel', []))
                            if rel & {
                                'stylesheet',
                                'icon',
                                'apple-touch-icon',
                                'mask-icon',
                                'manifest',
                                'preload',
                                'modulepreload',
                            }:
                                urls.append(tag['href'])
                        for tag in soup.select('a[href]'):
                            target = urljoin(url, tag['href'])
                            if urlsplit(target).hostname in self.allowed_hosts:
                                if not re.search(
                                    r'/(logout|auth|admin)(/|$)', urlsplit(target).path
                                ):
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

    def export(self, destination):
        return Export(self).write(destination)


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
            wget,
            '--mirror',
            '--page-requisites',
            '--no-parent',
            '--adjust-extension',
            '--wait=1',
            '--random-wait',
            '--limit-rate=10m',
            '--timeout=60',
            '--tries=3',
            '--user-agent=' + USER_AGENT,
            '--directory-prefix=' + str(root / 'downloads'),
            '--warc-file=' + str(raw),
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
        staged = root / 'finished' / host
        capture.export(staged)
        validate(capture, staged, executable)
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
