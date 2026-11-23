import { describe, expect, it } from 'vitest';
import { LIVE_LINE } from './sentences';

describe('the live estimate line', () => {
  it('keeps the clause the design record quotes and names the files it does not weigh', () => {
    // DEC-26 item 1 quotes the first clause, so it stays a substring.
    expect(LIVE_LINE).toContain(
      'Live estimate: reads test and build results and file paths, not what your goal says.',
    );
    expect(LIVE_LINE).toContain('Files written by shell commands, such as a build, are not seen.');
  });
});
