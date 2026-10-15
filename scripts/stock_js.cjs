// SPDX-License-Identifier: GPL-3.0-only

const acorn = require('acorn');

module.exports = function stockEdits(source, origin) {
    if (origin !== 'https://diyhrt.coffee/') return [];
    if (!source.includes('reconnecting...') && !source.includes(' synced')) return [];
    const edits = [];
    function walk(node) {
        if (!node || typeof node !== 'object') return;
        if (
            node.type === 'ConditionalExpression' &&
            node.consequent.value === 'watching' &&
            node.alternate.value === 'offline'
        ) {
            edits.push([
                node.start,
                node.end,
                'window.__mirror.stockStatus(' + source.slice(node.test.start, node.test.end) + ')'
            ]);
        } else if (node.type === 'Literal' && node.value === ' synced') {
            edits.push([node.start, node.end, 'window.__mirror.stockLabel()']);
        } else if (node.type === 'Literal' && node.value === 'reconnecting...') {
            edits.push([node.start, node.end, JSON.stringify('loading saved status...')]);
        } else if (
            node.type === 'Literal' &&
            node.value === 'stock checked about every 30 seconds'
        ) {
            edits.push([
                node.start,
                node.end,
                JSON.stringify('stock checked about every 2 minutes')
            ]);
        }
        for (const child of Object.values(node)) {
            if (Array.isArray(child)) child.forEach(walk);
            else if (child && typeof child === 'object') walk(child);
        }
    }
    walk(acorn.parse(source, { ecmaVersion: 'latest' }));
    return edits;
};
