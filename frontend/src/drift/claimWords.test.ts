import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { claimMessage, holdsClaimWord } from './claimWords';

const entry = (id: string, summary: string) => ({ id, summary }) as never;

describe('claimMessage', () => {
  const exited = entry('m1', 'The worker stopped before the queue had registered the new job.');
  const fixed = entry(
    'm2',
    'I fixed the one failing check on the widget guard, and it now passes.',
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

/* The page's word list is a hand copy of the two rules the model is told, so read the rules from the producer
   and hold every word they name. A word added or dropped there fails here. */
describe('the claim words match the producer rules', () => {
  const source = readFileSync(
    resolve(process.cwd(), 'compass/skills/compass/compass_runtime/reading.py'),
    'utf8',
  );
  const full = /compare agent states \(([^)]*)\)/.exec(source.replace(/'\s*\n\s*"/g, ''));
  const short = /only assertions of ([a-z/]+),/.exec(source);
  const words = (list: string): string[] =>
    list
      .split(/[,/]/)
      .map((word) => word.trim())
      .filter(Boolean);

  it('finds both rules', () => {
    expect(full).not.toBeNull();
    expect(short).not.toBeNull();
  });

  it('holds every word of both rules, passing in its three forms', () => {
    const named = [...words(full?.[1] ?? ''), ...words(short?.[1] ?? '')];
    expect(named.length).toBeGreaterThanOrEqual(9);
    for (const word of named) expect(holdsClaimWord(`it is ${word} now`)).toBe(true);
    for (const form of ['passing', 'passes', 'passed']) expect(holdsClaimWord(form)).toBe(true);
  });
});
