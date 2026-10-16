# SPDX-License-Identifier: GPL-3.0-only

import json
from pathlib import Path
import subprocess
import unittest


SCRIPTS = Path(__file__).resolve().parent


class StockAppTests(unittest.TestCase):
    def test_panel_labels_distinguish_live_checks_from_saved_results(self):
        javascript = """
const assert = require('node:assert/strict');
const stockEdits = require('./scripts/stock_js.cjs');
const original = `const title = connected ? 'watching' : 'offline';
const label = count + ' synced'; const pending = 'reconnecting...';
const timing = 'stock checked about every 30 seconds'; const text = 'keep synced text';`;
let output = original;
const edits = stockEdits(original, 'https://diyhrt.coffee/');
for (const [start, end, text] of edits.sort((a, b) => b[0] - a[0]))
    output = output.slice(0, start) + text + output.slice(end);
assert.match(output, /stockStatus\(connected\)/);
assert.match(output, /stockLabel\(\)/);
assert.match(output, /loading saved status/);
assert.match(output, /every 2 minutes/);
assert.match(output, /keep synced text/);
assert.deepEqual(stockEdits(original, 'https://valerie.vg/'), []);
"""
        subprocess.run(['node', '-e', javascript], cwd=SCRIPTS.parent, check=True)

    def test_live_socket_and_reads_use_independent_service_with_saved_fallback(self):
        runtime = (SCRIPTS / 'local_app.js').read_text()
        javascript = """
const assert = require('node:assert/strict');
const vm = require('node:vm');
const requests = [];
let remoteFails = false;
let native;
class NativeSocket {
    constructor(url) {this.url = url; native = this;}
    close() {this.onclose?.();}
}
const saved = {
    '/diyhrt.coffee/shops.json': [{id:9,name:'Aurelia',enabled:true,lastPollOk:true,lastPollAt:'2026-01-01T00:00:00Z'}],
    '/diyhrt.coffee/current.json': [{shopId:9,itemId:444,inStock:false}],
    '/diyhrt.coffee/me.json': {user:null},
};
const records = {};
for (const [name, file, status] of [['shops','shops',200],['stock/current','current',200],['me','me',401]])
    records['https://diyhrt.coffee/api/v1/'+name] = {path:'/diyhrt.coffee/'+file+'.json',status,type:'application/json'};
const window = {
    __mirror: {original:'https://diyhrt.coffee/',root:'/diyhrt.coffee/',
        stockEndpoint:'https://stock.cmyksoda.cc',origins:{'https://diyhrt.coffee':'/diyhrt.coffee/'},records},
    WebSocket: NativeSocket, addEventListener() {},
    fetch: async (url, options) => {
        requests.push([url, options]);
        if (url.startsWith('https://stock.cmyksoda.cc')) {
            assert.equal(options.credentials, 'omit');
            assert.equal(options.headers, undefined);
            if (remoteFails) throw new Error('Service offline');
            return new Response(JSON.stringify([{shopId:9,itemId:444,inStock:true}]));
        }
        return new Response(JSON.stringify(saved[url]));
    },
};
class Element {setAttribute() {}}
class XMLHttpRequest {open() {}}
class CloseEvent extends Event {constructor(type, options) {super(type);Object.assign(this, options);}}
const context = {window, Element, XMLHttpRequest, URL, Response, Request, Map, EventTarget, Event,
    MessageEvent, CloseEvent, DOMException, AbortSignal, queueMicrotask, setTimeout, clearTimeout,
    document:{readyState:'complete'}, navigator:{onLine:true},
    location:{href:'https://mirror.example/diyhrt.coffee/',origin:'https://mirror.example'}, console};
for (const type of ['HTMLImageElement','HTMLScriptElement','HTMLLinkElement','HTMLAnchorElement','HTMLSourceElement','HTMLVideoElement']) context[type] = Element;
vm.runInNewContext(RUNTIME, context);
(async () => {
    const socket = new window.WebSocket('wss://mirror.example/ws');
    const messages = [];
    socket.onmessage = event => messages.push(JSON.parse(event.data));
    assert.equal(native.url, 'wss://stock.cmyksoda.cc/ws');
    native.onopen();
    assert.equal(window.__mirror.stockStatus(true), 'watching');
    assert.equal(window.__mirror.stockLabel(), ' synced');
    const live = await window.fetch('/diyhrt.coffee/current.json', {headers:{'X-Client-Id':'private'}});
    assert.equal((await live.json())[0].inStock, true);
    assert.equal(requests[0][0], 'https://stock.cmyksoda.cc/api/v1/stock/current');
    assert.equal((await window.fetch('/api/v1/me')).status, 401);
    assert.equal((await window.fetch('/api/v1/reviews', {method:'POST'})).status, 503);
    remoteFails = true;
    const fallback = await window.fetch('/api/v1/stock/current');
    assert.equal((await fallback.json())[0].inStock, false);
    await new Promise(setImmediate);
    assert.equal(window.__mirror.stockStatus(false), 'archived');
    assert.equal(window.__mirror.stockLabel(), ' saved');
    assert.equal(messages[0].shop, 'Aurelia');
    assert.equal(messages[0].timestamp, '2026-01-01T00:00:00Z');
    assert.equal(messages[0].tracked, 1);
    assert.ok(requests.every(([url]) => !url.startsWith('https://diyhrt.coffee')));
    const remoteCount = requests.filter(([url]) => url.startsWith('https:')).length;
    window.__mirrorOffline = true;
    const offline = new window.WebSocket('wss://mirror.example/ws');
    await new Promise(setImmediate);
    assert.equal(offline.readyState, window.WebSocket.CLOSED);
    assert.equal(requests.filter(([url]) => url.startsWith('https:')).length, remoteCount);
})().catch(error => {console.error(error); process.exitCode = 1;});
""".replace('RUNTIME', json.dumps(runtime))
        subprocess.run(['node', '-e', javascript], check=True)


if __name__ == '__main__':
    unittest.main()
