import { describe, expect, it } from 'vitest';
import { blockedBackend, fakeBackend, readOnlyBackend } from '../../test/storage_backends';
import { compatSessKey } from '../api/identity';
import { createLegacyStorage, memoKey, sessionKey, STORAGE_KEYS } from '.';

describe('the retired live estimate family (compass.next.live-estimate:)', () => {
  const session = { harness: 'claude', sid: 'a b:c' };

  it('is no longer a family: the Live monitor is a lease the server holds, so nothing of it is stored', () => {
    expect(Object.keys(STORAGE_KEYS)).not.toContain('liveEstimatePrefix');
    const backend = fakeBackend({ 'compass.next.live-estimate:claude:a b:c': '1' });
    const storage = createLegacyStorage(() => backend);
    expect(Object.keys(storage)).not.toContain('liveEstimate');
    expect(backend.writes).toEqual([]);
  });

  it('keys a row with no sid on its display id, as the page does, and agrees with the API layer', () => {
    const row = { harness: 'claude', sid: '', session: 'abcd1234' };
    expect(sessionKey(row)).toBe(compatSessKey(row));
    expect(memoKey('p', row, 'focus')).toBe('compass.cockpit.memo.v2:p:claude%3Aabcd1234:focus');
    expect(sessionKey(session)).toBe(compatSessKey(session));
  });
});

describe('workstream collapse family (compass.next.workstream.collapsed)', () => {
  const key = 'compass.next.workstream.collapsed';

  it('is collapsed only for the raw word 1', () => {
    expect(Object.values(STORAGE_KEYS)).toContain(key);
    for (const [raw, expected] of [
      ['1', true],
      ['0', false],
      ['true', false],
      ['', false],
    ] as const) {
      expect(createLegacyStorage(() => fakeBackend({ [key]: raw })).workstream.collapsed()).toBe(
        expected,
      );
    }
    expect(createLegacyStorage(() => fakeBackend()).workstream.collapsed()).toBe(false);
    expect(createLegacyStorage(() => blockedBackend()).workstream.collapsed()).toBe(false);
  });

  it('writes 1 or 0 and updates the tab before persisting', () => {
    const backend = fakeBackend();
    const { workstream } = createLegacyStorage(() => backend);
    expect(workstream.setCollapsed(true)).toBe(true);
    expect(backend.data.get(key)).toBe('1');
    workstream.setCollapsed(false);
    expect(backend.data.get(key)).toBe('0');
    const refused = createLegacyStorage(() => readOnlyBackend()).workstream;
    expect(refused.setCollapsed(true)).toBe(false);
    expect(refused.collapsed()).toBe(true);
  });

  it('reads storage once, as the legacy module does at load, then answers from the tab', () => {
    const backend = fakeBackend({ [key]: '1' });
    const { workstream } = createLegacyStorage(() => backend);
    expect(workstream.collapsed()).toBe(true);
    backend.data.set(key, '0');
    expect(workstream.collapsed()).toBe(true);
  });
});

describe('the eleven keys', () => {
  it('are spelled exactly as released', () => {
    expect(STORAGE_KEYS).toEqual({
      memoPrefix: 'compass.cockpit.memo.v2:',
      graphMode: 'compass.next.graph.mode',
      guardrailPrefix: 'compass.next.guardrails.',
      leader: 'compass.next.leader',
      revision: 'compass.next.revision',
      usageConsent: 'compass.next.usage.consent',
      workstreamCollapsed: 'compass.next.workstream.collapsed',
      observerConsent: 'compass.observer-model-consent.v1',
      cockpitProject: 'compass.projectCockpitProject',
      goalPrefix: 'compass.projectGoal.v1:',
      usage: 'compass.projectUsage.v1',
    });
  });
});
