# SPDX-License-Identifier: GPL-3.0-only

import json
from pathlib import Path
import subprocess
import unittest


class ReplayTests(unittest.TestCase):
    def test_event_replay_accepts_read_only_event_dictionaries(self):
        bundle = (Path(__file__).resolve().parents[1] / 'replay/sw.js').read_text()
        start = bundle.index('function NewEventConstructor(type, init)')
        end = bundle.index(r'\n  })(ConstructorFN);', start)
        constructor = json.loads('"' + bundle[start:end] + '"').rstrip(';')
        script = """
const assert = require('node:assert/strict');
const realWindow = {};
const proxyWindow = {};
const wombat = {
    domConstructorErrorChecker() {},
    proxyToObj(value) { return value === proxyWindow ? realWindow : value; },
};
const which = 'MouseEvent';
class EventConstructor {
    constructor(type, init) {
        this.type = type;
        this._view = init.view;
        this._relatedTarget = init.relatedTarget;
        this.bubbles = init.bubbles;
        this.clientX = init.clientX;
    }
    get view() { return this._view; }
    get relatedTarget() { return this._relatedTarget; }
}
const ReplayEvent = CONSTRUCTOR;
const original = new EventConstructor('click', {
    view: proxyWindow, relatedTarget: proxyWindow, bubbles: true, clientX: 42,
});
const clone = new ReplayEvent(original.type, original);
assert.equal(clone.type, 'click');
assert.equal(clone.view, realWindow);
assert.equal(clone.relatedTarget, realWindow);
assert.equal(clone.bubbles, true);
assert.equal(clone.clientX, 42);
assert.equal(original.view, proxyWindow);
const frozen = Object.freeze({view: proxyWindow, bubbles: false, clientX: 7});
const fromFrozen = new ReplayEvent('click', frozen);
assert.equal(fromFrozen.view, realWindow);
assert.equal(fromFrozen.bubbles, false);
assert.equal(fromFrozen.clientX, 7);
assert.equal(frozen.view, proxyWindow);
""".replace('CONSTRUCTOR', constructor)
        subprocess.run(['node', '--use-strict', '-'], input=script, text=True, check=True)
