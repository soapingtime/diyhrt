// SPDX-License-Identifier: GPL-3.0-only

(() => {
    const config = window.__mirror;
    const records = config.records;
    const origin = new URL(config.original).origin;
    const fetchFile = window.fetch.bind(window);
    const NativeSocket = window.WebSocket;
    const stockPaths = new Set([
        '/api/v1/shops',
        '/api/v1/items',
        '/api/v1/stock/current',
        '/api/v1/stock/changes'
    ]);
    let stockLive = false;
    let stockSocket;
    let savedStock;
    config.stockStatus = connected => (connected && stockLive ? 'watching' : 'archived');
    config.stockLabel = () => (stockLive ? ' synced' : ' saved');
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
        const original = sourceURL(value);
        if (stockLive && original.origin === origin && stockPaths.has(original.pathname)) {
            try {
                const signal = AbortSignal.timeout(5000);
                const response = await fetchFile(
                    config.stockEndpoint + original.pathname + original.search,
                    {
                        method,
                        credentials: 'omit',
                        cache: 'no-store',
                        signal: options.signal ? AbortSignal.any([options.signal, signal]) : signal
                    }
                );
                if (!response.ok) throw new Error('Live stock unavailable');
                return response;
            } catch (error) {
                if (options.signal?.aborted) throw error;
                stockLive = false;
                stockSocket?.close();
            }
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

    function savedStockEvents() {
        if (!savedStock) {
            savedStock = Promise.all(
                ['shops', 'stock/current'].map(async endpoint => {
                    const record = records[origin + '/api/v1/' + endpoint];
                    if (!record) return [];
                    return (await fetchFile(record.path)).json();
                })
            ).then(([shops, current]) =>
                shops
                    .filter(shop => shop.enabled)
                    .map(shop => ({
                        type: shop.lastPollOk === false ? 'poll.error' : 'poll.success',
                        shop: shop.name,
                        timestamp: shop.lastPollAt || '',
                        tracked: current.filter(row => row.shopId === shop.id).length,
                        changed: false
                    }))
            );
        }
        return savedStock;
    }

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

    class StockSocket extends EventTarget {
        static CONNECTING = 0;
        static OPEN = 1;
        static CLOSING = 2;
        static CLOSED = 3;
        readyState = StockSocket.CONNECTING;
        bufferedAmount = 0;
        protocol = '';
        extensions = '';
        binaryType = 'blob';
        stopped = false;

        constructor(url) {
            super();
            this.url = String(url);
            if (config.stockEndpoint && !window.__mirrorOffline && navigator.onLine) {
                const endpoint = new URL('/ws', config.stockEndpoint);
                endpoint.protocol = endpoint.protocol === 'https:' ? 'wss:' : 'ws:';
                this.socket = new NativeSocket(endpoint.href);
                this.timeout = setTimeout(() => this.socket.close(), 5000);
                stockSocket = this.socket;
                this.socket.onopen = () => {
                    clearTimeout(this.timeout);
                    stockLive = true;
                    this.readyState = StockSocket.OPEN;
                    this.emit(new Event('open'));
                };
                this.socket.onmessage = event =>
                    this.emit(new MessageEvent('message', { data: event.data }));
                this.socket.onclose = () => this.fallback();
            } else {
                queueMicrotask(() => this.fallback());
            }
        }

        emit(event) {
            this.dispatchEvent(event);
            this['on' + event.type]?.(event);
        }

        async fallback() {
            clearTimeout(this.timeout);
            stockLive = false;
            if (this.stopped) return;
            try {
                for (const event of await savedStockEvents()) {
                    if (this.stopped) return;
                    this.emit(new MessageEvent('message', { data: JSON.stringify(event) }));
                }
            } finally {
                this.readyState = StockSocket.CLOSED;
                this.emit(new CloseEvent('close', { code: 1000, reason: 'Archived snapshot' }));
            }
        }

        close() {
            clearTimeout(this.timeout);
            this.stopped = true;
            this.readyState = StockSocket.CLOSED;
            this.socket?.close();
        }

        send(data) {
            if (this.readyState !== StockSocket.OPEN)
                throw new DOMException('The stock connection is closed.', 'InvalidStateError');
            this.socket.send(data);
        }
    }

    window.WebSocket = origin === 'https://diyhrt.coffee' ? StockSocket : SnapshotSocket;
})();
