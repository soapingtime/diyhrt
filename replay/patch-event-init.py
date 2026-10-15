# SPDX-License-Identifier: AGPL-3.0-or-later

"""Apply the read-only EventInit fix to ReplayWeb.page 2.5.3's sw.js bundle."""

from pathlib import Path
import sys


BEFORE = """      if (init) {
        if (init.view != null) {
          init.view = wombat.proxyToObj(init.view);
        }
        if (init.relatedTarget != null) {
          init.relatedTarget = wombat.proxyToObj(init.relatedTarget);
        }
        if (init.target != null) {
          init.target = wombat.proxyToObj(init.target);
        }
      }
      return new EventConstructor(type, init);"""

AFTER = """      if (init) {
        // Local fix (2026-10-15): React may reuse a read-only Event as EventInit.
        var originalInit = init;
        init = new Proxy({}, {
          get: function(_target, name) {
            var value = Reflect.get(originalInit, name, originalInit);
            if (name === 'view' || name === 'relatedTarget' || name === 'target') {
              return wombat.proxyToObj(value);
            }
            return value;
          }
        });
      }
      return new EventConstructor(type, init);"""


if __name__ == '__main__':
    path = Path(sys.argv[1] if len(sys.argv) > 1 else 'replay/sw.js')
    text = path.read_text()
    before = BEFORE.replace('\n', r'\n')
    after = AFTER.replace('\n', r'\n')
    pointer_before = "  this.overrideAnUIEvent('MouseEvent');"
    pointer_after = pointer_before + r"\n  this.overrideAnUIEvent('PointerEvent');"
    if text.count(before) != 1:
        raise SystemExit('Expected the unmodified ReplayWeb.page 2.5.3 event wrapper')
    if text.count(pointer_before) != 1:
        raise SystemExit('Expected the unmodified UI event registration')
    path.write_text(text.replace(before, after).replace(pointer_before, pointer_after))
