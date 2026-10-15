// SPDX-License-Identifier: GPL-3.0-only

const acorn = require('acorn');
const fs = require('node:fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const mapping = input.mapping;
const origins = input.origins;
const resourceDirectories = new Set();
for (const [url, record] of Object.entries(mapping)) {
    if (record.type.startsWith('text/html')) continue;
    let directory = new URL('.', url);
    while (directory.pathname !== '/') {
        resourceDirectories.add(directory.href);
        directory = new URL('..', directory);
    }
}

function relocate(value, origin, allowRoot = false, pageURLs = false) {
    if (value === '/' && !allowRoot) return value;
    if (value === origin.replace(/\/$/, '')) return value;
    if (!value.startsWith('/') && !value.startsWith('https://')) return value;
    let url;
    try {
        url = new URL(value, origin);
    } catch {
        return value;
    }
    const hash = url.hash;
    url.hash = '';
    if (mapping[url.href]) {
        const record = mapping[url.href];
        if (!pageURLs && record.type.startsWith('text/html')) return value;
        return record.path + hash;
    }
    const prefix = origins[url.origin];
    if (
        prefix &&
        (resourceDirectories.has(url.href) ||
            /^\/(api|_next|static|mascot|counter|badges)\//.test(url.pathname))
    ) {
        return prefix + url.pathname.slice(1) + url.search + hash;
    }
    return value;
}

function cssURLs(value, origin) {
    return value.replace(
        /url\(\s*(['"]?)([^'")]+)\1\s*\)/g,
        (_match, quote, url) => 'url(' + quote + relocate(url.trim(), origin, true) + quote + ')'
    );
}

function flightJSON(value, origin, key = '') {
    if (Array.isArray(value)) return value.map(item => flightJSON(item, origin));
    if (value && typeof value === 'object') {
        return Object.fromEntries(
            Object.entries(value).map(([name, item]) => [
                name,
                key === 'style' && typeof item === 'string'
                    ? cssURLs(item, origin)
                    : flightJSON(item, origin, name)
            ])
        );
    }
    if (typeof value === 'string') {
        if (['href', 'src', 'poster', 'action'].includes(key) || value.startsWith('/_next/')) {
            return relocate(value, origin, true, true);
        }
    }
    return value;
}

function flight(stream, origin, canonical) {
    const bytes = Buffer.from(stream);
    const output = [];
    let position = 0;
    while (position < bytes.length) {
        const colon = bytes.indexOf(58, position);
        if (colon < 0) throw new Error('Incomplete Flight record');
        if (bytes[colon + 1] === 84) {
            // T records count UTF-8 bytes, not JavaScript characters. Keep text intact.
            const comma = bytes.indexOf(44, colon + 2);
            const size = Number.parseInt(bytes.subarray(colon + 2, comma).toString(), 16);
            const end = comma + 1 + size;
            if (!Number.isFinite(size) || end > bytes.length)
                throw new Error('Invalid Flight text length');
            output.push(bytes.subarray(position, end).toString());
            position = end;
            continue;
        }
        let end = bytes.indexOf(10, colon);
        if (end < 0) end = bytes.length;
        const header = bytes.subarray(position, colon + 1).toString();
        const body = bytes.subarray(colon + 1, end).toString();
        const start = body.search(/[\[{]/);
        let changed = body;
        if (start >= 0) {
            try {
                let value = JSON.parse(body.slice(start));
                value = flightJSON(value, origin);
                if (
                    header === '0:' &&
                    canonical &&
                    value &&
                    !Array.isArray(value) &&
                    Array.isArray(value.c)
                ) {
                    value.c = canonical;
                }
                changed = body.slice(0, start) + JSON.stringify(value);
            } catch (error) {
                if (body.startsWith('{') || body.startsWith('[')) throw error;
            }
        }
        output.push(header + changed + (end < bytes.length ? '\n' : ''));
        position = end + 1;
    }
    return output.join('');
}

function walk(node, callback, ancestors = []) {
    if (!node || typeof node !== 'object') return;
    callback(node, ancestors);
    for (const value of Object.values(node)) {
        if (Array.isArray(value)) value.forEach(item => walk(item, callback, [...ancestors, node]));
        else if (value && typeof value === 'object') walk(value, callback, [...ancestors, node]);
    }
}

const groups = new Map();
for (const item of input.items) {
    item.flightTokens = [];
    if (!item.group) continue;
    walk(acorn.parse(item.source, { ecmaVersion: 'latest' }), node => {
        if (
            node.type !== 'CallExpression' ||
            node.callee.type !== 'MemberExpression' ||
            node.callee.property.name !== 'push'
        )
            return;
        const argument = node.arguments[0];
        if (
            argument?.type !== 'ArrayExpression' ||
            argument.elements[0]?.value !== 1 ||
            typeof argument.elements[1]?.value !== 'string'
        )
            return;
        const token = argument.elements[1];
        const entry = { item, token };
        if (!groups.has(item.group)) groups.set(item.group, []);
        groups.get(item.group).push(entry);
        item.flightTokens.push(entry);
    });
}
for (const entries of groups.values()) {
    const last = entries.at(-1);
    const stream = entries.map(entry => entry.token.value).join('');
    const rewritten = flight(stream, last.item.origin, last.item.canonical);
    // Deliver the complete stream after the saved server-rendered DOM has parsed.
    for (const entry of entries) entry.value = entry === last ? rewritten : '';
}

const output = [];
for (const item of input.items) {
    if (item.stream) {
        output.push(flight(item.source, item.origin, item.canonical));
        continue;
    }
    const source = item.source;
    const edits = item.flightTokens.map(entry => [
        entry.token.start,
        entry.token.end,
        JSON.stringify(entry.value)
    ]);
    if (source.includes('hydrateRoot')) {
        walk(acorn.parse(source, { ecmaVersion: 'latest' }), node => {
            if (node.type !== 'CallExpression' || !node.arguments.length) return;
            const callee =
                node.callee.type === 'SequenceExpression'
                    ? node.callee.expressions.at(-1)
                    : node.callee;
            if (callee.type !== 'MemberExpression' || callee.property.name !== 'hydrateRoot')
                return;
            const renderer = source.slice(callee.object.start, callee.object.end);
            edits.push([node.callee.start, node.callee.end, 'window.__mirror.mount']);
            edits.push([node.arguments[0].start, node.arguments[0].start, renderer + ',']);
        });
    }
    if (source.includes('usePathname')) {
        walk(acorn.parse(source, { ecmaVersion: 'latest' }), (node, ancestors) => {
            if (node.type !== 'Property' || (node.key.name || node.key.value) !== 'usePathname')
                return;
            const getter = node.value;
            const result =
                getter.body?.type === 'Identifier'
                    ? getter.body
                    : getter.body?.body?.find(n => n.type === 'ReturnStatement')?.argument;
            if (result?.type !== 'Identifier') return;
            for (const parent of [...ancestors].reverse()) {
                if (!parent.body || parent.body.type !== 'BlockStatement') continue;
                const declaration = parent.body.body.find(
                    n => n.type === 'FunctionDeclaration' && n.id?.name === result.name
                );
                if (!declaration) continue;
                const returned = declaration.body.body.find(
                    n => n.type === 'ReturnStatement'
                )?.argument;
                if (
                    returned &&
                    source.slice(returned.start, returned.end).includes('PathnameContext')
                ) {
                    edits.push([
                        returned.start,
                        returned.end,
                        'window.__mirror.pathname((' +
                            source.slice(returned.start, returned.end) +
                            '))'
                    ]);
                }
                break;
            }
        });
    }
    const flightStarts = new Set(item.flightTokens.map(entry => entry.token.start));
    for (const token of acorn.tokenizer(source, { ecmaVersion: 'latest', allowHashBang: true })) {
        if (token.type.label !== 'string' || flightStarts.has(token.start)) continue;
        const value = token.value;
        const href = /(?:href|src|action)\s*:\s*$/.test(
            source.slice(Math.max(0, token.start - 20), token.start)
        );
        let changed = cssURLs(relocate(value, item.origin, href), item.origin);
        if (changed !== value) edits.push([token.start, token.end, JSON.stringify(changed)]);
    }
    let text = source;
    for (const [start, end, value] of edits.sort((a, b) => b[0] - a[0])) {
        text = text.slice(0, start) + value + text.slice(end);
    }
    output.push(text);
}
process.stdout.write(JSON.stringify(output));
