import { describe, expect, it } from 'vitest';
import { blockedBackend, fakeBackend, readOnlyBackend } from '../../test/storage_backends';
import { createLegacyStorage, decodeGuardrails, guardrailKey, normalizeGuardrail } from '.';

describe('guardrail family (compass.next.guardrails.)', () => {
  it('keys on the encoded project', () => {
    expect(guardrailKey('my project/é')).toBe('compass.next.guardrails.my%20project%2F%C3%A9');
  });

  it('accepts the older plain-string rules as enabled', () => {
    expect(decodeGuardrails('["watch tests", {"text":"b","enabled":false}]')).toEqual([
      { enabled: true, text: 'watch tests' },
      { enabled: false, text: 'b' },
    ]);
  });

  it('loads an older 500-unit rule unchanged and reloads a new rule beyond the old cap', () => {
    const old = '界'.repeat(500);
    const backend = fakeBackend({ [guardrailKey('p')]: JSON.stringify([old]) });
    const { guardrails } = createLegacyStorage(() => backend);
    expect(guardrails.rules('p')).toEqual([{ enabled: true, text: old }]);
    const text = '😀'.repeat(1000);
    guardrails.add('p', text);
    expect(createLegacyStorage(() => backend).guardrails.rules('p')[1]?.text).toBe(text);
  });

  it('disables only on an explicit false and drops empty or invalid rules', () => {
    const raw = JSON.stringify([
      { text: 'a', enabled: 0 },
      { text: 'b', enabled: null },
      { text: '   ' },
      { text: 5 },
      null,
      7,
      [],
      { enabled: true },
      { text: 'c', enabled: false },
    ]);
    expect(decodeGuardrails(raw)).toEqual([
      { enabled: true, text: 'a' },
      { enabled: true, text: 'b' },
      { enabled: false, text: 'c' },
    ]);
  });

  it('trims and bounds loaded text to 2000 code points without splitting emoji', () => {
    const rule = normalizeGuardrail('  ' + 'a'.repeat(1999) + '😀 tail  ');
    expect(rule?.text).toBe('a'.repeat(1999) + '😀');
    expect(normalizeGuardrail('😀'.repeat(2100))?.text).toBe('😀'.repeat(2000));
    expect(normalizeGuardrail('x'.repeat(2001))?.text).toHaveLength(2000);
  });

  it('keeps the first fifty valid rules when more are stored', () => {
    const rules = [null, null, ...Array.from({ length: 60 }, (_, index) => `rule ${index}`)];
    const loaded = decodeGuardrails(JSON.stringify(rules));
    expect(loaded).toHaveLength(50);
    expect(loaded[0]?.text).toBe('rule 0');
    expect(loaded[49]?.text).toBe('rule 49');
  });

  it('reads corrupt JSON and non-arrays as no rules', () => {
    expect(decodeGuardrails('{not json')).toEqual([]);
    expect(decodeGuardrails('{"text":"a"}')).toEqual([]);
    expect(decodeGuardrails('"a"')).toEqual([]);
    expect(decodeGuardrails(null)).toEqual([]);
  });

  it('writes rules in the released JSON shape and refuses a fifty-first rule without changing any', () => {
    const backend = fakeBackend();
    const { guardrails } = createLegacyStorage(() => backend);
    const added = guardrails.add('p', '  first  ');
    expect(added.persisted).toBe(true);
    expect(backend.data.get(guardrailKey('p'))).toBe('[{"enabled":true,"text":"first"}]');
    for (let index = 0; index < 49; index += 1) guardrails.add('p', `r${index}`);
    const before = guardrails.rules('p');
    const writes = backend.writes.length;
    expect(guardrails.add('p', 'one too many')).toEqual({
      rules: before,
      persisted: true,
      refused: 'limit',
    });
    expect(guardrails.rules('p')).toEqual(before);
    expect(backend.writes).toHaveLength(writes);
    const stored = JSON.parse(backend.data.get(guardrailKey('p')) ?? '[]') as { text: string }[];
    expect(stored).toHaveLength(50);
    expect(stored[0]?.text).toBe('first');
    expect(stored[49]?.text).toBe('r48');
  });

  it('refuses an empty rule without touching storage', () => {
    const backend = fakeBackend();
    const { guardrails } = createLegacyStorage(() => backend);
    expect(guardrails.add('p', '   ').rules).toEqual([]);
    expect(backend.writes).toEqual([]);
  });

  it('removes the rendered rule, persists, and refuses a rule that no longer matches', () => {
    const backend = fakeBackend({ [guardrailKey('p')]: '["a","b","c"]' });
    const { guardrails } = createLegacyStorage(() => backend);
    const target = guardrails.rules('p')[1];
    if (!target) throw new Error('Missing rendered rule');
    expect(guardrails.remove('p', target)).toEqual({
      rules: [
        { enabled: true, text: 'a' },
        { enabled: true, text: 'c' },
      ],
      persisted: true,
    });
    expect(createLegacyStorage(() => backend).guardrails.rules('p')).toEqual(guardrails.rules('p'));
    const writes = backend.writes.length;
    expect(guardrails.remove('p', target).refused).toBe('stale');
    expect(backend.writes).toHaveLength(writes);
  });

  it.each(['add', 'toggle', 'remove'] as const)(
    're-reads storage before %s so another tab’s saved rule is never dropped',
    (action) => {
      const backend = fakeBackend({
        [guardrailKey('p')]: JSON.stringify(Array.from({ length: 49 }, (_, n) => `r${n}`)),
      });
      const a = createLegacyStorage(() => backend).guardrails;
      const b = createLegacyStorage(() => backend).guardrails;
      const rendered = a.rules('p');
      expect(rendered).toHaveLength(49);
      const target = rendered[0];
      if (!target) throw new Error('Missing rendered rule');
      b.add('p', 'B saved this');
      const writes = backend.writes.length;
      const result = action === 'add' ? a.add('p', 'A’s refused draft') : a[action]('p', target);
      if (action === 'add') {
        expect(result.refused).toBe('limit');
        expect(backend.writes).toHaveLength(writes);
      }
      const stored = createLegacyStorage(() => backend).guardrails.rules('p');
      expect(stored.at(-1)?.text).toBe('B saved this');
      expect(stored).toHaveLength(action === 'remove' ? 49 : 50);
    },
  );

  it('toggles the rendered rule and persists, refusing an outdated enabled state', () => {
    const backend = fakeBackend({ [guardrailKey('p')]: '["a","b"]' });
    const { guardrails } = createLegacyStorage(() => backend);
    const target = guardrails.rules('p')[1];
    if (!target) throw new Error('Missing rendered rule');
    expect(guardrails.toggle('p', target).rules).toEqual([
      { enabled: true, text: 'a' },
      { enabled: false, text: 'b' },
    ]);
    expect(backend.data.get(guardrailKey('p'))).toBe(
      '[{"enabled":true,"text":"a"},{"enabled":false,"text":"b"}]',
    );
    const before = backend.writes.length;
    expect(guardrails.toggle('p', target).refused).toBe('stale');
    expect(backend.writes).toHaveLength(before);
  });

  it.each(['remove', 'toggle'] as const)(
    'targets a duplicate text by its rendered enabled state when another tab removes a preceding rule (%s)',
    (action) => {
      const backend = fakeBackend({
        [guardrailKey('p')]: '["A","same",{"text":"same","enabled":false},"C"]',
      });
      const a = createLegacyStorage(() => backend).guardrails;
      const b = createLegacyStorage(() => backend).guardrails;
      const target = a.rules('p')[2];
      const first = b.rules('p')[0];
      if (!target || !first) throw new Error('Missing rendered rule');
      b.remove('p', first);
      const result = a[action]('p', target);
      expect(result.refused).toBeUndefined();
      expect(result.rules).toEqual(
        action === 'remove'
          ? [
              { enabled: true, text: 'same' },
              { enabled: true, text: 'C' },
            ]
          : [
              { enabled: true, text: 'same' },
              { enabled: true, text: 'same' },
              { enabled: true, text: 'C' },
            ],
      );
      expect(createLegacyStorage(() => backend).guardrails.rules('p')).toEqual(result.rules);
    },
  );

  it('toggles the second identical duplicate when the rendered list is unchanged', () => {
    const backend = fakeBackend({ [guardrailKey('p')]: '["same","same"]' });
    const { guardrails } = createLegacyStorage(() => backend);
    const target = guardrails.rules('p')[1];
    if (!target) throw new Error('Missing rendered rule');
    expect(guardrails.toggle('p', target).rules).toEqual([
      { enabled: true, text: 'same' },
      { enabled: false, text: 'same' },
    ]);
  });

  it.each(['remove', 'toggle'] as const)(
    'refreshes ambiguous identical duplicates without writing until the reader retries (%s)',
    (action) => {
      const backend = fakeBackend({ [guardrailKey('p')]: '["same","same","C"]' });
      const a = createLegacyStorage(() => backend).guardrails;
      const b = createLegacyStorage(() => backend).guardrails;
      const target = a.rules('p')[1];
      const first = b.rules('p')[0];
      if (!target || !first) throw new Error('Missing rendered rule');
      b.remove('p', first);
      const writes = backend.writes.length;
      const result = a[action]('p', target);
      expect(result).toEqual({
        rules: [
          { enabled: true, text: 'same' },
          { enabled: true, text: 'C' },
        ],
        persisted: true,
        refused: 'stale',
      });
      expect(a.rules('p')).toEqual(result.rules);
      expect(backend.writes).toHaveLength(writes);
      const refreshed = result.rules[0];
      if (!refreshed) throw new Error('Missing refreshed rule');
      expect(a[action]('p', refreshed).refused).toBeUndefined();
      expect(createLegacyStorage(() => backend).guardrails.rules('p')).toEqual(
        action === 'remove'
          ? [{ enabled: true, text: 'C' }]
          : [
              { enabled: false, text: 'same' },
              { enabled: true, text: 'C' },
            ],
      );
    },
  );

  it('serves later reads from tab memory so a failed write or read does not lose rules', () => {
    const { guardrails } = createLegacyStorage(() => readOnlyBackend());
    const change = guardrails.add('p', 'kept');
    expect(change.persisted).toBe(false);
    expect(guardrails.rules('p')).toEqual([{ enabled: true, text: 'kept' }]);
    const blocked = createLegacyStorage(() => blockedBackend()).guardrails;
    expect(blocked.rules('p')).toEqual([]);
    expect(blocked.add('p', 'still works').rules).toEqual([{ enabled: true, text: 'still works' }]);
  });

  it('does not hand out its internal array', () => {
    const { guardrails } = createLegacyStorage(() => fakeBackend());
    const first = guardrails.add('p', 'a').rules;
    guardrails.add('p', 'b');
    expect(first).toHaveLength(1);
  });
});
