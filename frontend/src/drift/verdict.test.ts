import { describe, expect, it } from 'vitest';
import type { WorkEntry } from '../intent/work';
import { clock } from '../observed';
import { citedLine, indexEntries, localRecordedTime, verdictLine, type Answer } from './result';
import type { Criterion } from './shape';

const entry = (id: string, at: number, extra: Partial<WorkEntry> = {}): WorkEntry =>
  ({
    id,
    type: 'agent_message',
    by: 'agent',
    summary: 'Done: the billing rate is now 0.25.',
    at,
    subject: '',
    result: '',
    ...extra,
  }) as WorkEntry;

const row = (key: string, cites: string[]): Criterion =>
  ({ key, citedIds: cites, result: 'departure' }) as unknown as Criterion;

const departs = (rows: Criterion[]): Answer => ({
  kind: 'departs',
  count: rows.length,
  departures: rows,
});

describe('the Drift card verdict sentence', () => {
  const message = entry('m', 1000);
  const write = entry('w', 900, { type: 'tool_report', subject: 'write', summary: 'src/a.ts' });
  const byId = indexEntries([message, write]);

  it('says the level, the count and the one entry both departures rest on', () => {
    expect(
      verdictLine({
        answer: departs([row('goal', ['m']), row('line_1', ['m'])]),
        level: 'Medium',
        byId,
        midFlight: false,
      }),
    ).toBe(`Medium: 2 departures, both at the agent's message at ${clock(1000)}.`);
  });

  it('names two different entries, and counts more than two with their span', () => {
    expect(
      verdictLine({
        answer: departs([row('goal', ['m', 'w'])]),
        level: 'High',
        byId,
        midFlight: false,
      }),
    ).toBe(
      `High: 1 departure, at the agent's message at ${clock(1000)} and a file write at ${clock(900)}.`,
    );
    const third = entry('u', 1100, { type: 'user_message', by: 'person:me' });
    expect(
      verdictLine({
        answer: departs([row('goal', ['m', 'w', 'u'])]),
        level: 'Medium',
        byId: indexEntries([message, write, third]),
        midFlight: false,
      }),
    ).toBe(`Medium: 1 departure, citing 3 entries from ${clock(900)} to ${clock(1100)}.`);
  });

  it('never puts a level word on an answer the reading could not settle', () => {
    for (const kind of ['cant-tell', 'not-reached'] as const) {
      const text = verdictLine({ answer: { kind }, level: 'None or low', byId, midFlight: false });
      expect(text).not.toContain('None or low');
    }
  });

  it('says a reading of a running session answers for the work so far', () => {
    expect(
      verdictLine({
        answer: departs([row('goal', ['m'])]),
        level: 'Medium',
        byId,
        midFlight: true,
      }),
    ).toMatch(/^Medium so far: 1 departure/);
  });
});

describe("a departure's What", () => {
  it("quotes the agent's words, attributed, bounded and without a drawn check mark", () => {
    expect(citedLine(entry('m', 1))).toBe('Agent said: “Done: the billing rate is now 0.25.”');
    expect(citedLine(entry('m', 1, { summary: 'Done ✓ ships' }))).toBe(
      'Agent said: “Done [check mark] ships”',
    );
    const long = citedLine(entry('m', 1, { summary: 'word '.repeat(80) }));
    expect(long.length).toBeLessThan(230);
    expect(long.endsWith('…”')).toBe(true);
    expect(
      citedLine(
        entry('c', 1, {
          type: 'tool_report',
          subject: 'check',
          result: 'failed',
          summary: 'pytest',
        }),
      ),
    ).toBe('Failed check: pytest');
  });
});

describe('recorded times on the page', () => {
  it("are the reader's local time, with the date", () => {
    const at = 1_792_458_900;
    const date = new Date(at * 1000);
    const two = (n: number) => String(n).padStart(2, '0');
    expect(localRecordedTime(at)).toBe(
      `${String(date.getFullYear())}-${two(date.getMonth() + 1)}-${two(date.getDate())} ${clock(at)}:${two(date.getSeconds())}`,
    );
    expect(localRecordedTime(null)).toBe('time not recorded');
  });
});
