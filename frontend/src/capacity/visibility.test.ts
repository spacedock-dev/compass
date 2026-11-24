import { describe, expect, it } from 'vitest';
import { hidesQuota, quotaShown, withoutHiddenQuota } from './visibility';

const payload = {
  generated: 1,
  usage: [
    { harness: 'claude', state: 'ok', fiveH: { pct: 38 } },
    { harness: 'cursor', state: 'ok', month: { pct: 5 } },
    { harness: 'codex', state: 'ok', fiveH: { pct: 71 } },
    { harness: 'antigravity', state: 'ok', fiveH: { pct: 20 } },
  ],
};

describe('Turn off quota reading, as every quota surface applies it', () => {
  it('keeps every row while the switch is on, as the same payload', () => {
    expect(withoutHiddenQuota(payload, false)).toBe(payload);
    expect(quotaShown('claude', false)).toBe(true);
    expect(hidesQuota(payload, false)).toBe(false);
  });

  it('keeps only the local readings while it is off, whichever source filled the Claude row', () => {
    const shown = withoutHiddenQuota(payload, true);
    expect(shown.usage.map(({ harness }) => harness)).toEqual(['codex', 'antigravity']);
    expect(hidesQuota(payload, true)).toBe(true);
    expect(quotaShown('claude', true)).toBe(false);
    expect(quotaShown('codex', true)).toBe(true);
  });

  it('returns one copy per payload, so a selector reading it stays stable between renders', () => {
    expect(withoutHiddenQuota(payload, true)).toBe(withoutHiddenQuota(payload, true));
  });

  it('says nothing is hidden when no credential-backed row was published', () => {
    expect(hidesQuota({ usage: [{ harness: 'codex' }] }, true)).toBe(false);
    expect(hidesQuota({}, true)).toBe(false);
  });
});
