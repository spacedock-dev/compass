import { describe, expect, it } from 'vitest';
import { ENDED_CAVEAT } from './sentences';

/* What the notice governs: on a session that has ended, Analyze reads the intent saved before the end, or a goal
   taken from one of the reader's prompts. Anything typed and saved after the end is kept but not read. */
describe('the ended-session notice', () => {
  it('says what a reader can still do, and what saving now does and does not do', () => {
    expect(ENDED_CAVEAT).toBe(
      'This session has ended. What you save now is kept, but Analyze will not check the session against it. Analyze still uses the intent you saved before the session ended, or a goal taken from one of your prompts.',
    );
  });

  it('avoids the phrase "read against", which a new reader cannot parse', () => {
    expect(ENDED_CAVEAT).not.toMatch(/read against|drafted/i);
  });
});
