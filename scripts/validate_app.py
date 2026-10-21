# SPDX-License-Identifier: GPL-3.0-only

"""Check every exported page before replacing a working mirror."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_arguments):
        pass


def validate(capture, destination, executable=None):
    destination = Path(destination)
    root = destination.parent
    handler = partial(QuietHandler, directory=str(root))
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = 'http://127.0.0.1:' + str(server.server_port)
    errors = []
    current = ['initial']

    def error(message):
        errors.append((current[0], message))

    try:
        with sync_playwright() as playwright:
            options = {'headless': True}
            if executable:
                options['executable_path'] = executable
            browser = playwright.chromium.launch(**options)
            context = browser.new_context(viewport={'width': 1280, 'height': 900})
            # Validate the complete saved copy independently of the optional live stock service.
            context.add_init_script('window.__mirrorOffline = true;')
            page = context.new_page()

            def guard(route):
                url = route.request.url
                if url.startswith((base + '/', 'data:', 'blob:')):
                    route.continue_()
                else:
                    errors.append((current[0], 'External request: ' + url))
                    route.abort()

            page.route('**/*', guard)
            page.on('pageerror', lambda exception: error(str(exception)))
            page.on(
                'console', lambda message: error(message.text) if message.type == 'error' else None
            )
            page.on(
                'response',
                lambda response: (
                    errors.append((current[0], str(response.status) + ' ' + response.url))
                    if response.status >= 400
                    else None
                ),
            )
            for url, local in sorted(capture.exported_pages.items()):
                current[0] = url
                page.goto(base + local, wait_until='load', timeout=60000)
                page.evaluate('''async () => {
                    for (let y = 0; y < document.body.scrollHeight; y += 700) {
                        scrollTo(0, y);
                        await new Promise(resolve => setTimeout(resolve, 8));
                    }
                }''')
                page.wait_for_load_state('networkidle')
                if not page.locator('body').inner_text().strip():
                    errors.append((url, 'Empty document after loading'))
                source = capture.responses[url]
                soup = BeautifulSoup(
                    (capture.directory / source['file']).read_bytes(), 'html.parser'
                )
                if soup.h1 and not page.locator('h1').count():
                    errors.append((url, 'The page heading disappeared'))
                missing = page.locator('img').evaluate_all('''images => images
                    .filter(image => image.getClientRects().length && image.complete && !image.naturalWidth)
                    .map(image => image.src)''')
                errors.extend((url, 'Broken image: ' + image) for image in missing)
                print('checked:', url, flush=True)
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    if errors:
        details = '\n'.join(url + ': ' + message for url, message in errors)
        raise RuntimeError('The exported mirror failed validation:\n' + details)
    print(
        'Validated',
        len(capture.exported_pages),
        'pages with no missing resources or external requests',
        flush=True,
    )
