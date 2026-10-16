# SPDX-License-Identifier: GPL-3.0-only

"""Export captured pages and public responses as ordinary local files."""

from datetime import datetime, timezone
import hashlib
import json
import mimetypes
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import quote, unquote, urljoin, urlsplit

from bs4 import BeautifulSoup
import tinycss2


SCRIPTS = Path(__file__).resolve().parent
STOCK_ENDPOINT = 'https://stock.cmyksoda.cc'


class Export:
    def __init__(self, capture):
        self.capture = capture
        self.root = '/' + capture.host + '/'
        self.origins = {'https://' + capture.host: self.root}
        if capture.host == 'diyhrt.coffee':
            self.origins['https://forum.diyhrt.coffee'] = self.root + 'forum/'
        self.records = {}
        self.javascript = []
        self.product_groups = {}
        if capture.host == 'valerie.vg':
            for url in capture.pages:
                path = urlsplit(url).path
                if not path.startswith('/meds/groups/'):
                    continue
                slug = path.rstrip('/').rsplit('/', 1)[-1]
                body = (capture.directory / capture.responses[url]['file']).read_bytes()
                for link in BeautifulSoup(body, 'html.parser').select('a[href]'):
                    product = urlsplit(urljoin(url, link['href'])).path.rstrip('/')
                    if product.startswith('/meds/products/'):
                        self.product_groups.setdefault(product, set()).add(slug)

    def filename(self, url, record):
        parts = urlsplit(url)
        kind = record['content_type']
        digest = hashlib.sha256(url.encode()).hexdigest()[:24]
        prefix = '' if parts.hostname == self.capture.host else 'forum/'
        page = url in self.capture.pages
        if parts.hostname not in self.capture.allowed_hosts:
            prefix = '_assets/'
            suffix = (
                Path(parts.path).suffix or mimetypes.guess_extension(kind.split(';')[0]) or '.bin'
            )
            return prefix + digest + suffix
        if parts.query:
            if page:
                return prefix + '_pages/' + digest + '.html'
            suffix = (
                Path(parts.path).suffix or mimetypes.guess_extension(kind.split(';')[0]) or '.txt'
            )
            return prefix + '_data/' + digest + suffix
        path = unquote(parts.path).lstrip('/')
        if any(segment in ('.', '..') for segment in Path(path).parts):
            raise ValueError('Unsafe captured path: ' + url)
        if page or record['location']:
            if path.endswith(('.html', '.htm')):
                return prefix + path
            return prefix + path.rstrip('/') + ('/' if path else '') + 'index.html'
        if not Path(path).suffix:
            suffix = mimetypes.guess_extension(kind.split(';')[0]) or '.bin'
            path += suffix
        return prefix + path

    def target(self, value, base):
        if not value or value.startswith(('#', 'data:', 'blob:', 'javascript:', 'mailto:')):
            return value
        url = urlsplit(urljoin(base, value))
        fragment = '#' + url.fragment if url.fragment else ''
        source = url._replace(fragment='').geturl()
        record = self.records.get(source)
        if record:
            return record['path'] + fragment
        if url.query:
            page = self.records.get(url._replace(query='', fragment='').geturl())
            if page and page['type'].startswith('text/html'):
                return page['path'] + '?' + url.query + fragment
        return value

    def css(self, text, base):
        def rewrite(tokens):
            importing = False
            for token in tokens:
                if token.type == 'at-keyword' and token.value.lower() == 'import':
                    importing = True
                elif token.type == 'literal' and token.value == ';':
                    importing = False
                if token.type == 'url':
                    token.value = self.target(token.value, base)
                    token.representation = 'url(' + json.dumps(token.value) + ')'
                elif token.type == 'string' and importing:
                    token.value = self.target(token.value, base)
                    token.representation = json.dumps(token.value)
                elif token.type == 'function' and token.lower_name == 'url':
                    for argument in token.arguments:
                        if argument.type == 'string':
                            argument.value = self.target(argument.value, base)
                            argument.representation = json.dumps(argument.value)
                for attribute in ('content', 'arguments'):
                    children = getattr(token, attribute, None)
                    if children:
                        rewrite(children)

        tokens = tinycss2.parse_component_value_list(text)
        rewrite(tokens)
        return tinycss2.serialize(tokens)

    def add_script(self, source, url, save, canonical=None, group=None, stream=False):
        self.javascript.append(
            {
                'source': source,
                'origin': 'https://' + urlsplit(url).netloc + '/',
                'canonical': canonical,
                'save': save,
                'group': group,
                'stream': stream,
            }
        )

    def html(self, body, url):
        soup = BeautifulSoup(self.capture.document(body), 'html.parser')
        if not soup.head:
            raise RuntimeError('Captured document has no head: ' + url)
        if self.capture.host == 'valerie.vg' and urlsplit(url).path.rstrip('/') == '/meds/products':
            groups = {}
            for option in soup.select('#id_product__drug_group option[value]'):
                slug = re.sub(r'[^a-z0-9]+', '-', option.get_text(strip=True).lower()).strip('-')
                groups[slug] = option['value']
            for link in soup.select('a.list-group-item[href]'):
                product = urlsplit(urljoin(url, link['href'])).path.rstrip('/')
                if product.startswith('/meds/products/'):
                    memberships = self.product_groups.get(product, set())
                    link['data-mirror-groups'] = ' '.join(
                        groups[group] for group in sorted(memberships) if group in groups
                    )
                    label = link.select_one('.col-7') or link
                    link['data-mirror-search'] = ' '.join(
                        label.get_text(' ', strip=True).split()
                    ).lower()
        for tag in list(soup.select('link[rel]')):
            if set(tag.get('rel', [])) & {'preconnect', 'dns-prefetch'}:
                tag.decompose()
        for tag in soup.select('[src], [href], [poster], [action], object[data]'):
            for attribute in ('src', 'href', 'poster', 'action', 'data'):
                if tag.get(attribute):
                    tag[attribute] = self.target(tag[attribute], url)
        for tag in soup.select('[srcset]'):
            if 'data:' not in tag['srcset']:
                entries = []
                for entry in tag['srcset'].split(','):
                    pieces = entry.split()
                    if pieces:
                        pieces[0] = self.target(pieces[0], url)
                        entries.append(' '.join(pieces))
                tag['srcset'] = ', '.join(entries)
        for tag in soup.select('[style]'):
            tag['style'] = self.css(tag['style'], url)
        for tag in soup.find_all('style'):
            tag.string = self.css(tag.get_text(), url)
        last_flight = None
        for tag in soup.find_all('script'):
            if tag.has_attr('src') or not tag.string:
                continue
            if tag.get('type') in ('application/json', 'application/ld+json'):
                continue
            canonical_path = self.records[url]['path'].removesuffix('index.html')
            canonical = canonical_path.split('/')
            group = url if '__next_f.push' in tag.string else None
            if re.search(r'__next_f\.push\(\s*\[\s*1\s*,', tag.string):
                last_flight = tag
            self.add_script(
                tag.string,
                url,
                lambda text, node=tag: setattr(node, 'string', text),
                canonical,
                group,
            )
        # Streamed suspense fragments must settle before hydration consumes the saved Flight stream.
        if last_flight and soup.body:
            soup.body.append(last_flight.extract())
        connections = "'self'"
        if self.capture.host == 'diyhrt.coffee':
            connections += ' ' + STOCK_ENDPOINT + ' ' + STOCK_ENDPOINT.replace('https:', 'wss:')
        policy = soup.new_tag(
            'meta',
            attrs={
                'http-equiv': 'Content-Security-Policy',
                'content': "default-src 'self' data: blob:; script-src 'self' 'unsafe-inline' 'unsafe-eval' blob:; "
                "style-src 'self' 'unsafe-inline'; connect-src "
                + connections
                + "; frame-src 'self'; "
                "form-action 'self'; base-uri 'self'",
            },
        )
        config = soup.new_tag('script')
        config.string = (
            'window.__mirror='
            + json.dumps(
                {
                    'original': url,
                    'root': self.root,
                    'origins': self.origins,
                    **(
                        {'stockEndpoint': STOCK_ENDPOINT}
                        if self.capture.host == 'diyhrt.coffee'
                        else {}
                    ),
                }
            ).replace('</', '<\\/')
            + ';'
        )
        resources = soup.new_tag('script', src=self.root + '_mirror/resources.js')
        runtime = soup.new_tag('script', src=self.root + '_mirror/runtime.js')
        for tag in reversed([policy, config, resources, runtime]):
            soup.head.insert(0, tag)
        return soup

    def write(self, destination):
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        shared_assets = {}
        for url, record in self.capture.responses.items():
            name = self.filename(url, record)
            kind = record['content_type']
            binary = not (
                kind.startswith('text/')
                or 'json' in kind
                or 'javascript' in kind
                or 'manifest' in kind
            )
            if binary and record['status'] == 200 and not record['location']:
                name = shared_assets.setdefault((record['file'], kind), name)
            public_name = (
                name.removesuffix('index.html')
                if url in self.capture.pages or record['location']
                else name
            )
            self.records[url] = {
                'path': self.root
                + quote(public_name, safe='/')
                + (
                    '?' + urlsplit(url).query
                    if url in self.capture.pages and urlsplit(url).query
                    else ''
                ),
                'file': name,
                'status': record['status'],
                'type': record['content_type'],
                'location': record['location'],
            }
        for url, record in self.records.items():
            seen = {url}
            target = record
            current = url
            while target['location']:
                current = urljoin(current, target['location'])
                if current not in self.records:
                    break
                if current in seen:
                    raise RuntimeError('Captured redirect loop: ' + url)
                seen.add(current)
                target = self.records[current]
                record['path'] = target['path']
        documents = []
        for url, record in self.capture.responses.items():
            local = self.records[url]
            path = destination / local['file']
            path.parent.mkdir(parents=True, exist_ok=True)
            body = (self.capture.directory / record['file']).read_bytes()
            if record['location']:
                target = self.target(urljoin(url, record['location']), url)
                path.write_text(
                    '<!doctype html><meta http-equiv="refresh" content="0; url=' + target + '">'
                )
            elif record['content_type'].startswith('text/html') and record['status'] == 200:
                documents.append((path, self.html(body, url)))
            elif record['content_type'].startswith('text/css'):
                path.write_text(self.css(body.decode(), url))
            elif record['content_type'].startswith('text/x-component'):
                self.add_script(body.decode(), url, path.write_text, stream=True)
            elif 'javascript' in record['content_type'] or urlsplit(url).path.endswith('.js'):
                self.add_script(body.decode(), url, path.write_text)
            else:
                path.write_bytes(body)
        payload = {
            'mapping': self.records,
            'origins': self.origins,
            'items': [
                {key: value for key, value in item.items() if key != 'save'}
                for item in self.javascript
            ],
        }
        result = subprocess.run(
            ['node', str(SCRIPTS / 'relocate_js.cjs')],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=True,
        )
        for item, text in zip(self.javascript, json.loads(result.stdout), strict=True):
            item['save'](text)
        for path, soup in documents:
            path.write_text(str(soup))
        support = destination / '_mirror'
        support.mkdir(exist_ok=True)
        resources = {
            url: {k: v for k, v in r.items() if k != 'file'} for url, r in self.records.items()
        }
        (support / 'resources.js').write_text(
            'window.__mirror.records=' + json.dumps(resources) + ';\n'
        )
        shutil.copyfile(SCRIPTS / 'local_app.js', support / 'runtime.js')
        pages = {url: self.records[url]['path'] for url in sorted(self.capture.pages)}
        self.capture.exported_pages = pages
        manifest = {
            'source': self.capture.origin,
            'captured': max(
                (page['ts'] for page in self.capture.pages.values()),
                default=datetime.now(timezone.utc).isoformat(),
            )[:10],
            'pages': pages,
            'responses': resources,
            'files': {
                str(path.relative_to(destination)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(destination.rglob('*'))
                if path.is_file() and path.name != 'archive.json'
            },
        }
        (destination / 'archive.json').write_text(json.dumps(manifest, indent=2) + '\n')
        return manifest
