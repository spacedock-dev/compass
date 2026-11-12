import { describe, expect, it } from 'vitest';
import { blockedBackend, fakeBackend, readOnlyBackend } from '../../test/storage_backends';
import { boundMemo, createLegacyStorage, memoKey } from '.';

describe('cockpit memo family (compass.cockpit.memo.v2:)', () => {
  it('loads a stored 500-unit memo unchanged and reloads a new memo beyond the old cap', () => {
    const key = memoKey('p', null, 'outcome');
    const old = '界'.repeat(500);
    const backend = fakeBackend({ [key]: old });
    const { memo } = createLegacyStorage(() => backend);
    expect(memo.read(key)).toBe(old);
    const text = '😀'.repeat(1000);
    memo.write(key, text);
    expect(createLegacyStorage(() => backend).memo.read(key)).toBe(text);
  });
  it('builds the released key: encoded project, encoded scope, kind', () => {
    expect(memoKey('proj/é', null, 'outcome')).toBe(
      'compass.cockpit.memo.v2:proj%2F%C3%A9:project:outcome',
    );
    expect(memoKey('k', { harness: 'claude', sid: 'a:b' }, 'focus')).toBe(
      'compass.cockpit.memo.v2:k:claude%3Aa%3Ab:focus',
    );
  });

  it('bounds to 2000 code points without splitting emoji, and non-strings read as empty', () => {
    expect(boundMemo('x'.repeat(2001))).toHaveLength(2000);
    const cut = boundMemo('a'.repeat(1999) + '😀');
    expect(cut).toBe('a'.repeat(1999) + '😀');
    const key = memoKey('p', null, 'focus');
    const { memo } = createLegacyStorage(() => fakeBackend({ [key]: '😀'.repeat(2100) }));
    expect(memo.read(key)).toBe('😀'.repeat(2000));
    expect(boundMemo(null)).toBe('');
    expect(boundMemo(5)).toBe('');
  });

  it('stores the bounded raw string with no wrapper, expiry or key-count cap', () => {
    const backend = fakeBackend();
    const { memo } = createLegacyStorage(() => backend);
    const key = memoKey('p', null, 'outcome');
    expect(memo.write(key, 'y'.repeat(2100))).toBe('saved');
    expect(backend.data.get(key)).toBe('y'.repeat(2000));
    expect(memo.state(key)).toBe('saved');
    for (let index = 0; index < 120; index += 1)
      memo.write(memoKey(`p${index}`, null, 'focus'), 'v');
    expect(backend.data.size).toBe(121);
  });

  it('reads the in-tab draft before storage and storage when there is no draft', () => {
    const key = memoKey('p', null, 'focus');
    const backend = fakeBackend({ [key]: 'from another tab' });
    const { memo } = createLegacyStorage(() => backend);
    expect(memo.read(key)).toBe('from another tab');
    memo.write(key, 'typed here');
    backend.data.set(key, 'changed elsewhere');
    expect(memo.read(key)).toBe('typed here');
  });

  it('refreshes a completed in-tab value without writing over a newer stored value', () => {
    const backend = fakeBackend();
    const { memo } = createLegacyStorage(() => backend);
    memo.write('key', 'typed here');
    backend.setItem('key', 'changed elsewhere');
    const writes = backend.writes.length;
    expect(memo.read('key', true)).toBe('changed elsewhere');
    expect(memo.read('key')).toBe('changed elsewhere');
    expect(backend.writes).toHaveLength(writes);
  });

  it('keeps a failed write in memory when a refresh finds storage unchanged', () => {
    const { memo } = createLegacyStorage(() => readOnlyBackend({ key: 'stored' }));
    expect(memo.read('key')).toBe('stored');
    expect(memo.write('key', 'only here')).toBe('error');
    expect(memo.read('key', true)).toBe('only here');
    expect(memo.restore('key', 'stored')).toBe('error');
    expect(memo.read('key')).toBe('stored');
  });

  it('does not write a restoration when it cannot check for another tab’s save', () => {
    const backend = fakeBackend({ key: 'original' });
    let denyReads = false;
    const { memo } = createLegacyStorage(() => ({
      ...backend,
      getItem: (key) => {
        if (denyReads) throw new DOMException('blocked', 'SecurityError');
        return backend.getItem(key);
      },
    }));
    memo.read('key');
    memo.write('key', 'typed here');
    backend.setItem('key', 'saved elsewhere');
    denyReads = true;
    const writes = backend.writes.length;
    expect(memo.restore('key', 'original')).toBe('error');
    expect(backend.data.get('key')).toBe('saved elsewhere');
    expect(backend.writes).toHaveLength(writes);
  });

  it('bounds what it reads from storage written by an older, longer editor', () => {
    const key = memoKey('p', null, 'focus');
    const { memo } = createLegacyStorage(() => fakeBackend({ [key]: 'z'.repeat(2100) }));
    expect(memo.read(key)).toHaveLength(2000);
  });

  it('reports a blocked read as an error state and an empty value, not as saved', () => {
    const key = memoKey('p', null, 'focus');
    const { memo } = createLegacyStorage(() => blockedBackend());
    expect(memo.read(key)).toBe('');
    expect(memo.state(key)).toBe('error');
  });

  it('keeps the draft for the tab when a write fails and says so', () => {
    const key = memoKey('p', null, 'focus');
    const { memo } = createLegacyStorage(() => readOnlyBackend());
    expect(memo.write(key, 'kept')).toBe('error');
    expect(memo.state(key)).toBe('error');
    expect(memo.read(key)).toBe('kept');
  });

  it('treats a missing Storage object like a blocked one', () => {
    const key = memoKey('p', null, 'focus');
    const { memo } = createLegacyStorage(() => null);
    expect(memo.write(key, 'v')).toBe('error');
    expect(memo.read(key)).toBe('v');
  });

  it('survives a provider that throws on access, as a sandboxed frame does', () => {
    const key = memoKey('p', null, 'focus');
    const { memo } = createLegacyStorage(() => {
      throw new DOMException('denied', 'SecurityError');
    });
    expect(memo.read(key)).toBe('');
    expect(memo.write(key, 'v')).toBe('error');
  });
});
