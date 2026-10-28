import { describe, expect, it } from 'vitest';
import { ciEntries, ciReadNote } from './ciRead';
import { ciReadReason } from './sentences';
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
  not_counted: 0,
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

  it('says the provider and the merge request’s own number sign for a GitLab read', () => {
    const gitlab = 'gitlab.example.com/acme/widgets';
    const note = ciReadNote(accepted({ repository: gitlab }), '10:00');
    expect(note.state).toBe('settles');
    expect(note.lines[0]).toBe(
      'Read from GitLab at 10:00: gitlab.example.com/acme/widgets!12, 2 passed, 1 skipped.',
    );
    const failed = ciReadNote(accepted({ repository: gitlab, error: 'rate-limited' }), 'x');
    expect(failed.lines[0]).toBe(
      'Merge request checks were not read from GitLab: GitLab is rate limiting your glab login.',
    );
    const unlisted = ciReadNote(
      accepted({ repository: gitlab, error: 'host-not-configured' }),
      'x',
    );
    expect(unlisted.lines[0]).toContain('does not name that GitLab host');
  });

  it('names glab, never gh, when a GitLab read comes back in a shape Compass does not read', () => {
    expect(ciReadReason('unreadable-output', 'GitLab')).toContain('glab');
    expect(ciReadReason('unreadable-output', 'GitLab')).not.toMatch(/\bgh\b/);
    for (const token of [
      'pull-request-not-found',
      'rate-limited',
      'timeout',
      'unreadable-output',
    ]) {
      expect(ciReadReason(token, 'GitLab')).not.toMatch(/\bgh\b/);
    }
  });

  it('rebuilds a GitLab read’s entries as GitLab words, so a cited job resolves', () => {
    const [first] = ciEntries(
      accepted({ repository: 'gitlab.example.com/acme/widgets' }),
      'claude',
      's1',
    );
    expect(first?.by).toBe('gitlab');
    expect(first?.source).toBe('GitLab merge request pipeline job, read by Compass · recorded');
    expect(first?.id).toBe('ci:12:0');
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

  it('says how many non-required checks the required-only rule left out', () => {
    const left = ciReadNote(accepted({ required_only: true, not_counted: 3 }), 'x');
    expect(left.lines).toContain('3 non-required checks not counted.');
    const one = ciReadNote(accepted({ required_only: true, not_counted: 1 }), 'x');
    expect(one.lines).toContain('1 non-required check not counted.');
    const none = ciReadNote(accepted({ required_only: true, not_counted: 0 }), 'x');
    expect(none.lines.join(' ')).not.toContain('not counted');
  });

  it('reads a record stored before the count was kept, and refuses a count with no rule behind it', () => {
    const older: Record<string, unknown> = record({ required_only: true });
    delete older['not_counted'];
    const ci = readingCi(older);
    expect(ci).not.toBeNull();
    expect(ciReadNote(ci as CiRead, 'x').lines.join(' ')).not.toContain('not counted');
    expect(readingCi(record({ not_counted: 2 }))).toBeNull();
    expect(readingCi(record({ required_only: true, not_counted: -1 }))).toBeNull();
    expect(readingCi(record({ required_only: true, not_counted: 1.5 }))).toBeNull();
  });

  it('says why a read never started for a harness with no recorded folder', () => {
    const note = ciReadNote(accepted({ error: 'no-session-folder', head_matches: false }), 'x');
    expect(note.state).toBe('failed');
    expect(note.lines[0]).toContain('no folder is known for this session');
  });

  it('words a read that never started for no folder, or no readable commit, by provider', () => {
    const gitlab = 'gitlab.example.com/acme/widgets';
    for (const token of ['no-session-folder', 'no-session-commit']) {
      expect(ciReadReason(token, 'GitLab')).toContain('merge request’s pipeline commit');
      expect(ciReadReason(token, 'GitLab')).not.toMatch(/\bpull request/);
      expect(ciReadReason(token, 'GitHub')).toContain('pull request’s commit');
      const note = ciReadNote(accepted({ repository: gitlab, error: token }), 'x');
      expect(note.state).toBe('failed');
      expect(note.lines[0]).toMatch(/^Merge request checks were not read from GitLab: /);
    }
    const noCommit = ciReadNote(
      accepted({ error: 'no-session-commit', head_matches: false, session_head: '' }),
      'x',
    );
    expect(noCommit.lines[0]).toContain('the commit this session is on could not be read');
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

    it('words a GitLab row as a merge request, in the entry and in the page sentence', () => {
      const repository = 'gitlab.example.com/acme/widgets';
      const [first] = ciEntries(accepted({ repository }), 'claude', 's1');
      expect(first?.summary).toBe('"lint" passed on the merge request');
      const moved = ciEntries(accepted({ repository, head_matches: false }), 'claude', 's1');
      expect(moved[0]?.summary).toContain("the merge request head is not this session's commit");
      expect(moved[0]?.summary).not.toContain('pull request');
    });
  });
});
