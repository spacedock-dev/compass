import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import { JSDOM } from 'jsdom';
import { measureSessionChrome, sessionChromeDifferences } from './session-chrome.mjs';

const table = JSON.parse(
  await readFile(new URL('../session-chrome-reference.json', import.meta.url), 'utf8'),
);

for (const [key, family] of [
  ['row|wide|next-operation-row--want', 'Inter, system-ui, -apple-system, sans-serif'],
  ['state|wide|', 'ui-monospace, monospace'],
]) {
  const recorded = table.instances[key];
  const row = { key, ...recorded, chrome: { ...recorded.chrome, 'font-family': family } };

  test(`the recorded ${key} accepts the ruled ${family} stack`, () => {
    assert.deepEqual(sessionChromeDifferences([row], table.instances), []);
  });

  test(`the recorded ${key} still rejects another family, a style change, or a width change`, () => {
    for (const changed of [
      { ...row, chrome: { ...row.chrome, 'font-family': 'Georgia, serif' } },
      { ...row, chrome: { ...row.chrome, 'font-size': '1px' } },
      { ...row, inlineSize: { ...row.inlineSize, ratio: recorded.inlineSize.ratio + 0.5 } },
    ]) {
      assert.equal(sessionChromeDifferences([changed], table.instances).length, 1);
    }
  });
}

test('a collapsed delivery surface fails the recorded width gate', () => {
  const dom = new JSDOM(
    '<div style="display:none"><section data-next-delivery><div data-slot="separator"></div></section></div>',
  );
  const saved = {
    document: globalThis.document,
    getComputedStyle: globalThis.getComputedStyle,
    innerWidth: globalThis.innerWidth,
  };
  Object.assign(globalThis, {
    document: dom.window.document,
    getComputedStyle: dom.window.getComputedStyle,
    innerWidth: 1280,
  });
  try {
    const [row] = measureSessionChrome();
    assert.ok(
      Number.isNaN(row.inlineSize.ratio),
      'zero width divided by zero width must reach the gate',
    );
    // Isolate the width gate from chrome, which a hidden rule also changes.
    row.chrome = table.instances[row.key].chrome;
    assert.equal(sessionChromeDifferences([row], table.instances).length, 1);
  } finally {
    Object.assign(globalThis, saved);
    dom.window.close();
  }
});

for (const invalid of [NaN, Infinity, -Infinity]) {
  for (const side of ['measured', 'expected']) {
    test(`${side} non-finite ratio ${invalid} fails`, () => {
      const row = {
        key: 'rule',
        chrome: {},
        inlineSize: { kind: 'row', ratio: side === 'measured' ? invalid : 1 },
      };
      const expected = {
        chrome: {},
        inlineSize: { kind: 'row', ratio: side === 'expected' ? invalid : 1 },
      };
      assert.equal(sessionChromeDifferences([row], { rule: expected }).length, 1);
    });
  }
}

test('matching recorded zero widths still pass', () => {
  const row = { key: 'rule', chrome: {}, inlineSize: { kind: 'row', ratio: 0 } };
  assert.deepEqual(sessionChromeDifferences([row], { rule: row }), []);
});
