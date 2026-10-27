import { describe, expect, it } from 'vitest';
import { ciEntries, ciReadNote } from './ciRead';
import { readingCi, readingShape, type CiRead } from './shape';

const HEAD = 'a'.repeat(40);
const record = (over: Record<string, unknown> = {}) => ({
  read_at: 1_000,
  error: '',
  source: 'goal',
  repository: 'acme/widgets',
  number: 12,
  head: HEAD,
  session_head: HEAD,
  head_matches: true,
  required_only: false,
  counts: { pass: 2, fail: 0, pending: 0, skipping: 1, cancel: 0 },
  caution: false,
  checks: [{ name: 'lint', bucket: 'pass', completed_at: 900 }],
  ...over,
});
/* A record the page accepts, or a failed test: the note is only drawn from one. */
const accepted = (over: Record<string, unknown> = {}): CiRead => {
  const ci = readingCi(record(over));
  if (!ci) throw new Error('the record was refused');
  return ci;
};
const counts = (over: Record<string, number>) => ({
  pass: 0,
  fail: 0,
  pending: 0,
  skipping: 0,
  cancel: 0,
  ...over,
});

describe('the pull request check read, as the card says it', () => {
  it('settles on green checks on the session’s commit and names skipped ones apart', () => {
    const note = ciReadNote(accepted(), '10:00');
    expect(note.state).toBe('settles');
    expect(note.lines[0]).toBe('Read from GitHub at 10:00: acme/widgets#12, 2 passed, 1 skipped.');
  });

  it.each([
    ['pending', counts({ pass: 1, pending: 1 }), 'Checks are still running'],
    ['cancelled', counts({ pass: 1, cancel: 1 }), 'A cancelled check keeps them'],
    ['no completed check', counts({ skipping: 2 }), 'No check has completed'],
  ])('%s settles nothing', (_name, bucketCounts, sentence) => {
    const note = ciReadNote(accepted({ counts: bucketCounts }), '10:00');
    expect(note.state).toBe('unsettled');
    expect(note.lines.join(' ')).toContain(sentence);
  });

  it('settles nothing when the head is not the session’s commit, or the commit is unknown', () => {
    const moved = ciReadNote(accepted({ head: 'b'.repeat(40), head_matches: false }), 'x');
    expect(moved.state).toBe('unsettled');
    expect(moved.lines.join(' ')).toContain('not this session’s commit');
    const unknown = ciReadNote(accepted({ session_head: '', head_matches: false }), 'x');
    expect(unknown.lines.join(' ')).toContain('could not read this session’s commit');
  });

  it('says a failing check counts, and carries the caution and the required-only note', () => {
    const note = ciReadNote(
      accepted({ counts: counts({ pass: 1, fail: 1 }), caution: true, required_only: true }),
      'x',
    );
    expect(note.lines.join(' ')).toContain('A failing check on this session’s commit counts');
    expect(note.lines).toContain('This session changed the CI configuration.');
    expect(note.lines).toContain('Only the checks GitHub requires are counted.');
  });

  it('says a failed read in a sentence of its own, from a closed token', () => {
    const note = ciReadNote(accepted({ error: 'gh-missing' }), 'x');
    expect(note.state).toBe('failed');
    expect(note.lines).toEqual([
      'Pull request checks were not read from GitHub: the gh command was not found on this machine.',
    ]);
  });

  it('refuses a record whose shape is not the producer’s, whole', () => {
    for (const bad of [
      record({ error: 'a sentence of its own' }),
      record({ extra: 1 }),
      record({ head: 'not-a-commit' }),
      record({ counts: { pass: 1 } }),
      record({ source: 'elsewhere' }),
      record({ checks: [{ name: 'x', bucket: 'mystery', completed_at: null }] }),
    ]) {
      expect(readingCi(bad)).toBeNull();
    }
    expect(readingCi(undefined)).toBeNull();
  });

  it('refuses a reading whose ci record it cannot read, rather than showing half of it', () => {
    const shape = readingShape(
      { revision_read: 1, ci: { error: 'nonsense' }, criteria: {} },
      null,
      [],
      '',
      false,
      () => '',
    );
    expect(shape.malformed).toContain('ci');
    expect(shape.ci).toBeNull();
  });

  describe('a line the model cites a check for', () => {
    const reading = (ci: Record<string, unknown>) => ({
      revision_read: 1,
      revision_read_at: 60,
      window_start: 50,
      read_at: 1_000,
      scope: 'final',
      scope_text: 'Read through the session end.',
      stamp: 'model · m',
      cutoff: 'Evidence read to its end.',
      ci,
      criteria: {
        goal: {
          result: 'consistent with the evidence read',
          cites: ['ci:12:0'],
          detail: '',
          clause: 'Fix CI',
          why: '',
        },
      },
    });
    const shape = (ci: Record<string, unknown>) =>
      readingShape(reading(ci), null, [], '', false, () => '');

    it('holds as consistent on green checks on the session’s commit, citing the checks', () => {
      const row = shape(record()).criteria.find((entry) => entry.key === 'goal');
      expect(row?.result).toBe('consistent with the evidence read');
      expect(row?.citedIds).toEqual(['ci:12:0']);
    });

    it.each([
      ['still running', record({ counts: counts({ pass: 2, pending: 1 }) })],
      [
        'on a head past the session’s commit',
        record({ head: 'b'.repeat(40), head_matches: false }),
      ],
    ])('is refused when the checks are %s', (_name, ci) => {
      const row = shape(ci).criteria.find((entry) => entry.key === 'goal');
      expect(row?.result).not.toBe('consistent with the evidence read');
    });

    it('builds the entries the producer numbered, with the same ids and words', () => {
      const [first] = ciEntries(accepted(), 'claude', 's1');
      expect(first?.id).toBe('ci:12:0');
      expect(first?.summary).toBe('"lint" passed on the pull request');
      expect(first?.ciCounts).toBe(true);
      const moved = ciEntries(accepted({ head_matches: false }), 'claude', 's1');
      expect(moved.every((entry) => entry.ciCounts === false)).toBe(true);
      expect(moved[0]?.summary).toContain("the pull request head is not this session's commit");
      expect(ciEntries(accepted({ error: 'gh-failed' }), 'claude', 's1')).toEqual([]);
    });
  });
});
