import { describe, expect, it } from 'vitest';
import { claimMessage, holdsClaimWord } from './claimWords';

const entry = (id: string, summary: string) => ({ id, summary }) as never;

describe('claimMessage', () => {
  const exited = entry(
    'm1',
    'The loop exited before CI had registered any checks for the new commit.',
  );
  const fixed = entry(
    'm2',
    'I fixed the one failing check on PR #7, the coverage gate, and it now passes.',
  );

  it('quotes the message that holds a claim word, not the first cited', () => {
    expect(claimMessage([exited, fixed])).toBe(fixed);
  });

  it('falls back to the first cited when none holds a claim word', () => {
    expect(claimMessage([exited, entry('m3', 'Looking at the queue now.')])).toBe(exited);
  });

  it('takes the first of several that hold one', () => {
    expect(claimMessage([fixed, entry('m4', 'Merged it.')])).toBe(fixed);
  });

  it('is null with nothing cited', () => {
    expect(claimMessage([])).toBeNull();
  });
});

describe('holdsClaimWord', () => {
  it('reads whole words, any case', () => {
    expect(holdsClaimWord('PASSED locally')).toBe(true);
    expect(holdsClaimWord('the sender fixedpoint undone')).toBe(false);
    expect(holdsClaimWord('')).toBe(false);
  });
});
