import { describe, expect, it } from 'vitest';
import { blockedBackend, fakeBackend, readOnlyBackend } from '../../test/storage_backends';
import { createLegacyStorage, STORAGE_KEYS } from '.';

const families = [
  ['usage consent', 'usageConsent', 'compass.next.usage.consent'],
  ['observer consent', 'observerConsent', 'compass.observer-model-consent.v1'],
] as const;

describe.each(families)('%s', (_name, family, key) => {
  it('uses the released key', () => {
    expect(Object.values(STORAGE_KEYS)).toContain(key);
  });

  it('is unanswered until someone answers, and a missing entry never reads as granted', () => {
    expect(createLegacyStorage(() => fakeBackend())[family].get()).toBeNull();
    expect(createLegacyStorage(() => fakeBackend({ [key]: 'yes' }))[family].get()).toBeNull();
    expect(createLegacyStorage(() => fakeBackend({ [key]: '' }))[family].get()).toBeNull();
    expect(createLegacyStorage(() => blockedBackend())[family].get()).toBeNull();
    expect(createLegacyStorage(() => null)[family].get()).toBeNull();
  });

  it('writes the raw word, collapsing anything but granted to declined', () => {
    const backend = fakeBackend();
    const store = createLegacyStorage(() => backend)[family];
    expect(store.set('granted')).toBe(true);
    expect(backend.data.get(key)).toBe('granted');
    store.set('declined');
    expect(backend.data.get(key)).toBe('declined');
    (store.set as (answer: string) => boolean)('maybe');
    expect(backend.data.get(key)).toBe('declined');
  });

  it('consults valid storage before the memo so another tab answer wins', () => {
    const backend = fakeBackend();
    const store = createLegacyStorage(() => backend)[family];
    store.set('granted');
    backend.data.set(key, 'declined');
    expect(store.get()).toBe('declined');
  });

  it('falls back to the memo when storage is unreadable or holds something unrecognised', () => {
    const backend = fakeBackend();
    const store = createLegacyStorage(() => backend)[family];
    store.set('granted');
    backend.data.set(key, 'garbled');
    expect(store.get()).toBe('granted');
  });

  it('treats an answer removed from storage as withdrawn, so a copy in memory cannot keep consent alive', () => {
    const backend = fakeBackend();
    const store = createLegacyStorage(() => backend)[family];
    expect(store.set('granted')).toBe(true);
    backend.data.delete(key);
    expect(store.get()).toBeNull();
  });

  it('holds the answer for the tab when the write is refused and reports it', () => {
    const store = createLegacyStorage(() => readOnlyBackend())[family];
    expect(store.set('granted')).toBe(false);
    expect(store.get()).toBe('granted');
    const blocked = createLegacyStorage(() => blockedBackend())[family];
    expect(blocked.set('declined')).toBe(false);
    expect(blocked.get()).toBe('declined');
  });
});

describe('the two consents', () => {
  it('uses the tab’s plan usage decline when a readable stored grant cannot be replaced', () => {
    const store = createLegacyStorage(() =>
      readOnlyBackend({ [STORAGE_KEYS.usageConsent]: 'granted' }),
    ).usageConsent;
    expect(store.get()).toBe('granted');
    expect(store.set('declined')).toBe(false);
    expect(store.get()).toBe('declined');
  });

  it('are independent keys and independent memos', () => {
    const backend = fakeBackend();
    const storage = createLegacyStorage(() => backend);
    storage.usageConsent.set('granted');
    expect(storage.observerConsent.get()).toBeNull();
    expect(backend.data.has('compass.observer-model-consent.v1')).toBe(false);
  });
});
