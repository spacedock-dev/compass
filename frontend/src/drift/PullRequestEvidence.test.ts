import { describe, expect, it } from 'vitest';
import { CONSISTENT, DEPARTURE } from './sentences';
import { checkSupports } from './shape';
import type { WorkEntry } from '../intent/work';

/* A created pull request or a launched skill shows something done and has no result to fail: the page's
   shape contract lets a reading cite either as consistent inside the window and as nothing else, the same as
   `reading.check_supports`
   ([DEC-23](../../../docs/design-reading-a-session.md#amended-2026-10-23-owner-pr-and-skill-facts)). */
const entry = (subject: string, at: unknown): WorkEntry =>
  ({
    id: 'e1',
    type: 'tool_report',
    subject,
    at,
    resultAt: null,
    summary: 'example-org/example-repo#7',
    source: 'Claude Bash call result',
  }) as unknown as WorkEntry;

describe('a pull request or skill entry in the shape contract', () => {
  it.each(['pr', 'skill'])('carries a consistent inside the window (%s)', (subject) => {
    expect(checkSupports(entry(subject, 150), CONSISTENT, 100)).toBe(true);
    expect(checkSupports(entry(subject, 150), CONSISTENT, null)).toBe(true);
  });

  it.each(['pr', 'skill'])(
    'carries no departure and nothing outside the window (%s)',
    (subject) => {
      expect(checkSupports(entry(subject, 150), DEPARTURE, 100)).toBe(false);
      expect(checkSupports(entry(subject, 50), CONSISTENT, 100)).toBe(false);
      expect(checkSupports(entry(subject, null), CONSISTENT, 100)).toBe(false);
      expect(checkSupports(entry(subject, 0), CONSISTENT, null)).toBe(false);
    },
  );
});
