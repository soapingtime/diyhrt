# SPDX-License-Identifier: GPL-3.0-only

"""Download a site and its page assets without replacing a working archive on failure.

Run with a hostname followed by optional seed URLs. External page requisites are
stored inside that site's _assets directory, so committing the site also commits
its fonts, styles, scripts and images. Ordinary external links are not crawled.
"""

import argparse
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.parse import quote, unquote, urljoin, urlsplit

from bs4 import BeautifulSoup
import requests
import tinycss2


POLICY = (
    "default-src 'self' data: blob:; script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; form-action 'none'"
)
USER_AGENT = 'Mozilla/5.0 (compatible; DIYHRTArchive/1.0; +https://github.com/soapingtime/diyhrt)'


def publish_snapshot(snapshot, destination, backup):
    if destination.exists():
        destination.rename(backup)
    try:
        snapshot.rename(destination)
    except OSError:
        if backup.exists():
            backup.rename(destination)
        raise


class Assets:
    def __init__(self, directory, origin, wait=1, static=False):
        self.directory = Path(directory).resolve()
        self.origin = origin.rstrip('/') + '/'
        self.wait = wait
        self.session = requests.Session()
        self.session.headers['User-Agent'] = USER_AGENT
        self.downloads = {}
        self.stylesheets = set()
        self.static = static
        self.custom_urls = {}

    def relative(self, target, source):
        relative = os.path.relpath(target, source.parent).replace(os.sep, '/')
        return quote(relative, safe='/.-_~')

    def local_file(self, url):
        parts = urlsplit(url)
        if parts.netloc != urlsplit(self.origin).netloc:
            return None
        path = self.directory / unquote(parts.path).lstrip('/')
        if not path.resolve().is_relative_to(self.directory):
            return None
        candidates = [Path(str(path) + ('?' + parts.query if parts.query else ''))]
        if not parts.query:
            candidates.extend([path / 'index.html', Path(str(path) + '.html')])
        for candidate in candidates:
            if candidate.is_file() and candidate.stat().st_size:
                return candidate
        return None

    def asset(self, value, base, source, stylesheet=False):
        if not value or value.startswith(('#', 'data:', 'blob:')):
            return value
        url = urljoin(base, value)
        parts = urlsplit(url)
        duplicate_host = '/' + urlsplit(self.origin).netloc + '/'
        if parts.netloc == urlsplit(self.origin).netloc and parts.path.startswith(duplicate_host):
            parts = parts._replace(path='/' + parts.path[len(duplicate_host) :])
        if parts.scheme not in ('http', 'https'):
            return value
        fragment = '#' + parts.fragment if parts.fragment else ''
        url = parts._replace(fragment='').geturl()
        target = self.local_file(url) or self.downloads.get(url)
        if target is None:
            time.sleep(self.wait)
            response = self.session.get(url, timeout=60)
            response.raise_for_status()
            if not response.content:
                raise ValueError('Empty asset: ' + url)
            content_type = response.headers.get('Content-Type', '').split(';')[0]
            suffix = Path(parts.path).suffix
            if content_type == 'text/css':
                suffix = '.css'
            elif 'javascript' in content_type:
                suffix = '.js'
            elif content_type == 'text/html':
                raise ValueError('Expected an asset, got HTML: ' + url)
            if len(suffix) > 12 or not suffix[1:].isalnum():
                suffix = ''
            digest = hashlib.sha256(url.encode()).hexdigest()[:24]
            target = self.directory / '_assets' / (digest + suffix)
            target.parent.mkdir(parents=True, exist_ok=True)
            self.downloads[url] = target
            target.write_bytes(response.content)
            if content_type == 'text/css' or suffix == '.css':
                self.stylesheets.add(target)
                target.write_text(self.css(response.text, response.url, target))
            print('asset:', url, flush=True)
        if stylesheet and target not in self.stylesheets:
            self.stylesheets.add(target)
            target.write_text(self.css(target.read_text(), url, target))
        return self.relative(target, source) + fragment

    def css(self, text, base, source, declarations=False):
        def rewrite(tokens, custom_property=None):
            for token in tokens:
                if token.type == 'ident' and token.value.startswith('--'):
                    custom_property = token.value
                elif token.type == 'literal' and token.value == ';':
                    custom_property = None
                if token.type == 'url':
                    if custom_property:
                        self.custom_urls.setdefault(custom_property, urljoin(base, token.value))
                    value = self.asset(token.value, base, source)
                    token.value = value
                    escaped = tinycss2.serializer.serialize_string_value(value)
                    token.representation = 'url("' + escaped + '")'
                elif token.type == 'function' and token.lower_name == 'url':
                    strings = [t for t in token.arguments if t.type == 'string']
                    if strings:
                        if custom_property:
                            self.custom_urls.setdefault(
                                custom_property, urljoin(base, strings[0].value)
                            )
                        value = self.asset(strings[0].value, base, source)
                        strings[0].value = value
                        escaped = tinycss2.serializer.serialize_string_value(value)
                        strings[0].representation = '"' + escaped + '"'
                if token.type == 'at-rule' and token.lower_at_keyword == 'import':
                    for part in token.prelude:
                        if part.type == 'string':
                            value = self.asset(part.value, base, source)
                            part.value = value
                            escaped = tinycss2.serializer.serialize_string_value(value)
                            part.representation = '"' + escaped + '"'
                            break
                for attr in ('content', 'arguments', 'prelude', 'value'):
                    children = getattr(token, attr, None)
                    if isinstance(children, list):
                        custom = custom_property
                        if token.type == 'declaration' and token.name.startswith('--'):
                            custom = token.name
                        rewrite(children, custom)

        parse = tinycss2.parse_declaration_list if declarations else tinycss2.parse_stylesheet
        tokens = parse(text, skip_comments=False, skip_whitespace=False)
        rewrite(tokens)
        return tinycss2.serialize(tokens)

    def html(self, path):
        relative = path.relative_to(self.directory).as_posix()
        base = urljoin(self.origin, relative)
        soup = BeautifulSoup(path.read_bytes(), 'html.parser')
        for tag in soup.find_all('base'):
            base = urljoin(base, tag.get('href', ''))
            tag.decompose()
        for tag in soup.select('meta[http-equiv]'):
            if tag['http-equiv'].lower() in ('content-security-policy', 'refresh'):
                tag.decompose()
        policy = soup.new_tag('meta')
        policy['http-equiv'] = 'Content-Security-Policy'
        policy['content'] = POLICY
        if soup.head:
            soup.head.insert(0, policy)
        if self.static:
            # Live app routers rehydrate absolute URLs and require APIs that a
            # static archive cannot serve. Keep their server-rendered document.
            for tag in soup.find_all('script'):
                tag.decompose()
            for tag in soup.select('link[as="script"], link[rel="modulepreload"]'):
                tag.decompose()
            for tag in soup.select('button, input, select, textarea'):
                tag['disabled'] = ''
                tag['title'] = 'Interactive control unavailable in this archived copy'
            for tag in soup.find_all('details'):
                tag['open'] = ''
            for tag in soup.select('.mw-collapsed'):
                tag['class'] = [name for name in tag['class'] if name != 'mw-collapsed']
            if soup.body:
                notice = soup.select_one('#archive-notice')
                if notice is None:
                    notice = soup.new_tag('aside', id='archive-notice')
                    soup.body.insert(0, notice)
                notice.clear()
                notice['style'] = (
                    'background: #fff; color: #111; padding: 1em; font: 16px sans-serif; '
                    'position: relative; z-index: 9999;'
                )
                notice.string = (
                    'Static archive. Content, prices and availability may be outdated. '
                    'Interactive features are available on the '
                )
                link = soup.new_tag('a', href=self.origin)
                link['style'] = 'color: #0044aa; text-decoration: underline;'
                link.string = 'original website'
                notice.append(link)
                notice.append('.')
        for tag in soup.select('script[src]'):
            if urlsplit(urljoin(base, tag['src'])).hostname == 'static.cloudflareinsights.com':
                tag.decompose()
        if urlsplit(self.origin).hostname == 'diyhrt.wiki':
            for tag in soup.select('script[src]'):
                if (
                    urlsplit(tag['src']).path.endswith('/age-check.js')
                    or tag['src'] == 'age-check.js'
                ):
                    tag.decompose()
        for tag in soup.select('link[href]'):
            rel = set(tag.get('rel', []))
            if rel & {'manifest', 'preconnect', 'dns-prefetch'}:
                tag.decompose()
            elif rel & {
                'stylesheet',
                'icon',
                'apple-touch-icon',
                'mask-icon',
                'preload',
                'modulepreload',
            }:
                tag['href'] = self.asset(tag['href'], base, path, stylesheet='stylesheet' in rel)
                tag.attrs.pop('integrity', None)
                tag.attrs.pop('crossorigin', None)
        media = (
            'script[src], img[src], source[src], video[src], audio[src], '
            'input[src], track[src], video[poster]'
        )
        for tag in soup.select(media):
            attr = 'poster' if tag.has_attr('poster') else 'src'
            try:
                tag[attr] = self.asset(tag[attr], base, path)
            except requests.HTTPError as error:
                if tag.name != 'img' or error.response.status_code not in (404, 410):
                    raise
                link = soup.new_tag('a', href=urljoin(base, tag[attr]))
                link.string = tag.get('alt') or '[image unavailable]'
                tag.replace_with(link)
                continue
            tag.attrs.pop('integrity', None)
            tag.attrs.pop('crossorigin', None)
        for tag in soup.select('[srcset]'):
            # Data URLs contain commas; leave them inline rather than splitting them.
            if 'data:' in tag['srcset']:
                raise ValueError('Mixed/data srcset needs review: ' + str(path))
            entries = []
            for entry in tag['srcset'].split(','):
                fields = entry.split()
                if fields:
                    fields[0] = self.asset(fields[0], base, path)
                    entries.append(' '.join(fields))
            tag['srcset'] = ', '.join(entries)
        for tag in soup.select('[style]'):
            # URLs inside CSS variables resolve where var() is used. An inline
            # style needs a path relative to its HTML document, not its CSS file.
            def variable(match):
                url = self.custom_urls.get(match.group(1))
                if url is None:
                    return match.group(0)
                value = self.asset(url, base, path)
                return 'url("' + tinycss2.serializer.serialize_string_value(value) + '")'

            style = tag['style']
            if self.static:
                style = re.sub(r'var\(\s*(--[\w-]+)\s*\)', variable, style)
            tag['style'] = self.css(style, base, path, declarations=True)
        for tag in soup.find_all('style'):
            tag.string = self.css(tag.get_text(), base, path)
        for tag in soup.select('a[href], iframe[src]'):
            attr = 'href' if tag.name == 'a' else 'src'
            original = urljoin(base, tag[attr])
            target = self.local_file(original)
            if target:
                fragment = urlsplit(tag[attr]).fragment
                tag[attr] = self.relative(target, path) + ('#' + fragment if fragment else '')
            elif tag.name == 'iframe':
                link = soup.new_tag('a', href=original)
                link.string = tag.get('title') or 'View embedded media on the original website'
                tag.replace_with(link)
            elif urlsplit(original).netloc == urlsplit(self.origin).netloc:
                tag[attr] = original
        path.write_text(str(soup), encoding='utf-8')

    def run(self):
        # Rewrite existing CSS before HTML starts fetching nested external styles.
        for path in list(self.directory.rglob('*.css')):
            if '_assets' not in path.relative_to(self.directory).parts:
                base = urljoin(self.origin, path.relative_to(self.directory).as_posix())
                self.stylesheets.add(path)
                path.write_text(self.css(path.read_text(), base, path))
        for path in list(self.directory.rglob('*')):
            if path.is_file() and path.suffix in ('.html', '.htm'):
                self.html(path)


def mirror(
    host,
    urls,
    reject,
    output=None,
    headers=(),
    static=False,
    level=None,
    ignore_robots=False,
    require_selector=None,
):
    if not host or '/' in host or host.startswith('.'):
        raise ValueError('Expected a hostname')
    origin = 'https://' + host + '/'
    destination = Path(output or host)
    with tempfile.TemporaryDirectory(prefix='.diyhrt-', dir=destination.parent) as temp:
        command = [
            'wget',
            '--mirror',
            '--page-requisites',
            '--convert-links',
            '--adjust-extension',
            '--backup-converted',
            '--no-parent',
            '--limit-rate=10m',
            '--wait=1',
            '--random-wait',
            '--timeout=60',
            '--tries=3',
            '--user-agent=' + USER_AGENT,
            '--domains=' + host,
            '--directory-prefix=' + temp,
        ]
        version = subprocess.run(['wget', '--version'], capture_output=True, text=True, check=True)
        if 'Wget2' in version.stdout:
            command.append('--max-threads=1')
        for header in headers:
            command.extend(['--header', header])
        if level is not None:
            command.append('--level=' + str(level))
        if ignore_robots:
            command.extend(['-e', 'robots=off'])
        if reject:
            command.append('--reject-regex=' + reject)
        result = subprocess.run(command + (urls or [origin]), check=False)
        # Wget uses 8 for individual HTTP errors, including stale internal links.
        # Other failures (DNS, TLS, disk, etc.) must not replace the last snapshot.
        if result.returncode not in (0, 8):
            raise RuntimeError('wget failed: ' + str(result.returncode))
        snapshot = Path(temp) / host
        assets = Assets(snapshot, origin, static=static)
        for url in urls or [origin]:
            page = assets.local_file(url)
            if not page:
                raise RuntimeError(
                    'Seed page not downloaded: ' + url + '; keeping the previous snapshot'
                )
            document = BeautifulSoup(page.read_bytes(), 'html.parser')
            content = document.select_one(require_selector) if require_selector else document.body
            if content is None or not content.get_text(strip=True):
                raise RuntimeError(
                    'Expected content missing: ' + url + '; keeping the previous snapshot'
                )
        assets.run()
        for path in snapshot.rglob('*.orig'):
            path.unlink()
        backup = Path(temp) / 'previous'
        publish_snapshot(snapshot, destination, backup)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host')
    parser.add_argument('urls', nargs='*')
    parser.add_argument('--reject', default='')
    parser.add_argument('--output')
    parser.add_argument('--header', action='append', default=[])
    parser.add_argument('--level', type=int)
    parser.add_argument('--ignore-robots', action='store_true')
    parser.add_argument(
        '--require-selector',
        help='require nonempty content matching this CSS selector on every seed page',
    )
    parser.add_argument(
        '--static',
        action='store_true',
        help='preserve server-rendered content without live app scripts or controls',
    )
    args = parser.parse_args()
    mirror(
        args.host,
        args.urls,
        args.reject,
        args.output,
        args.header,
        args.static,
        args.level,
        args.ignore_robots,
        args.require_selector,
    )


if __name__ == '__main__':
    main()
