import { describe, expect, it } from 'vitest';
import { sessionMeta } from './detail';

describe('the entries clause of the line under the title', () => {
  const session = { harness: 'claude', sid: 's', state: 'idle' };
  it('says a count read from the newest pages is a floor', () => {
    expect(sessionMeta(session, null, 50, null, true)).toContain('at least 50 entries');
  });
  it('states a whole record plainly', () => {
    const line = sessionMeta(session, null, 13, 4, false);
    expect(line).toContain('13 entries, 4 since your intent’s start');
    expect(line).not.toContain('at least');
  });
});
