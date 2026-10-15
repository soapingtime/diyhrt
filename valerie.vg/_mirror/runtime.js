// SPDX-License-Identifier: GPL-3.0-only

(() => {
    const config = window.__mirror;
    const records = config.records;
    const origin = new URL(config.original).origin;
    const fetchFile = window.fetch.bind(window);
    const reverse = new Map(
        Object.entries(records)
            .filter(([, record]) => !record.location)
            .map(([url, record]) => [new URL(record.path, location.href).pathname, url])
    );
    const origins = Object.entries(config.origins).sort((a, b) => b[1].length - a[1].length);

    function sourceURL(value) {
        const url = new URL(value, location.href);
        if (url.origin !== location.origin) return url;
        if (reverse.has(url.pathname)) {
            const original = new URL(reverse.get(url.pathname));
            original.search = url.search || original.search;
            original.hash = url.hash;
            return original;
        }
        for (const [host, prefix] of origins) {
            if (url.pathname === prefix.slice(0, -1)) {
                return new URL('/' + url.search + url.hash, host);
            }
            if (url.pathname.startsWith(prefix)) {
                return new URL(
                    url.pathname.slice(prefix.length) + url.search + url.hash,
                    host + '/'
                );
            }
        }
        return new URL(url.pathname + url.search + url.hash, origin);
    }

    function recordFor(value) {
        const url = sourceURL(value);
        url.hash = '';
        if (url.searchParams.has('_rsc')) url.searchParams.set('_rsc', 'archive');
        return records[url.href];
    }

    config.pathname = value => (value == null ? value : sourceURL(value).pathname);

    // Render saved React data afresh: relative times and streamed HTML cannot hydrate reliably later.
    config.mount = (renderer, container, element, options) => {
        const root = renderer.createRoot(container, options);
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => root.render(element), {
                once: true
            });
        } else {
            root.render(element);
        }
        return root;
    };

    function localURL(value) {
        if (!value || /^(#|data:|blob:|javascript:|mailto:)/.test(value)) return value;
        const url = sourceURL(value);
        const hash = url.hash;
        url.hash = '';
        const record = records[url.href];
        if (record) return record.path + hash;
        const query = url.search;
        url.search = '';
        const page = records[url.href];
        if (page && page.type.startsWith('text/html')) return page.path + query + hash;
        return value;
    }

    window.fetch = async (input, options = {}) => {
        const value = typeof input === 'string' || input instanceof URL ? String(input) : input.url;
        const method = options.method || input.method || 'GET';
        if (!['GET', 'HEAD'].includes(method.toUpperCase())) {
            return new Response('{"error":"This action requires the original site."}', {
                status: 503,
                headers: { 'Content-Type': 'application/json' }
            });
        }
        const record = recordFor(value);
        if (record) {
            if (record.location)
                return window.fetch(new URL(record.location, sourceURL(value)).href, options);
            const response = await fetchFile(record.path, { signal: options.signal });
            return new Response(method === 'HEAD' ? null : await response.arrayBuffer(), {
                status: record.status,
                headers: { 'Content-Type': record.type }
            });
        }
        const url = new URL(value, location.href);
        if (url.origin === location.origin && url.pathname.startsWith(config.root)) {
            return fetchFile(input, options);
        }
        console.error('Unrecorded request:', sourceURL(value).href);
        return new Response('{"error":"This response was not captured."}', {
            status: 503,
            headers: { 'Content-Type': 'application/json' }
        });
    };

    const open = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function (method, url, ...rest) {
        return open.call(this, method, localURL(String(url)), ...rest);
    };

    const setAttribute = Element.prototype.setAttribute;
    Element.prototype.setAttribute = function (name, value) {
        if (['src', 'href', 'poster', 'action'].includes(name)) value = localURL(String(value));
        return setAttribute.call(this, name, value);
    };
    for (const [type, names] of [
        [HTMLImageElement, ['src']],
        [HTMLScriptElement, ['src']],
        [HTMLLinkElement, ['href']],
        [HTMLAnchorElement, ['href']],
        [HTMLSourceElement, ['src']],
        [HTMLVideoElement, ['src', 'poster']]
    ]) {
        for (const name of names) {
            const descriptor = Object.getOwnPropertyDescriptor(type.prototype, name);
            if (!descriptor?.set) continue;
            Object.defineProperty(type.prototype, name, {
                ...descriptor,
                set(value) {
                    descriptor.set.call(this, localURL(String(value)));
                }
            });
        }
    }

    // Next's server navigation cannot run on a static host; use the captured documents.
    window.addEventListener(
        'click',
        event => {
            if (
                event.defaultPrevented ||
                event.button !== 0 ||
                event.metaKey ||
                event.ctrlKey ||
                event.shiftKey ||
                event.altKey
            )
                return;
            const anchor = event.target.closest?.('a[href]');
            if (!anchor || anchor.hasAttribute('download') || anchor.target === '_blank') return;
            const destination = localURL(anchor.href);
            const url = new URL(destination, location.href);
            if (url.origin !== location.origin || !url.pathname.startsWith(config.root)) return;
            if (url.pathname === location.pathname && url.search === location.search && url.hash)
                return;
            event.preventDefault();
            event.stopImmediatePropagation();
            location.assign(url.href);
        },
        true
    );

    // A saved CAPTCHA must never claim to have authenticated a visitor.
    window.turnstile = {
        render: (_element, options) => {
            queueMicrotask(() => options['error-callback']?.());
            return 'archive-service-unavailable';
        },
        reset() {},
        remove() {},
        getResponse: () => ''
    };

    window.addEventListener('DOMContentLoaded', () => {
        const group = document.getElementById('id_product__drug_group');
        if (!group || origin !== 'https://valerie.vg') return;
        const query = new URLSearchParams(location.search);
        const text = (query.get('q') || '').trim().toLowerCase();
        const selection = query.get('product__drug_group') || '';
        for (const input of document.querySelectorAll('input[name="q"]'))
            input.value = query.get('q') || '';
        group.value = selection;
        for (const product of document.querySelectorAll('[data-mirror-search]')) {
            const matchesText = product.dataset.mirrorSearch.includes(text);
            const matchesGroup =
                !selection || product.dataset.mirrorGroups.split(' ').includes(selection);
            product.style.display = matchesText && matchesGroup ? '' : 'none';
        }
    });

    // A saved snapshot has no live stock pushes; preserve the site's offline state.
    class SnapshotSocket extends EventTarget {
        static CONNECTING = 0;
        static OPEN = 1;
        static CLOSING = 2;
        static CLOSED = 3;
        readyState = SnapshotSocket.CLOSED;
        bufferedAmount = 0;
        protocol = '';
        extensions = '';
        binaryType = 'blob';
        constructor(url) {
            super();
            this.url = String(url);
            queueMicrotask(() => {
                const event = new CloseEvent('close', { code: 1000, reason: 'Archived snapshot' });
                this.dispatchEvent(event);
                this.onclose?.(event);
            });
        }
        close() {}
        send() {
            throw new DOMException('The archived connection is closed.', 'InvalidStateError');
        }
    }
    window.WebSocket = SnapshotSocket;
})();
