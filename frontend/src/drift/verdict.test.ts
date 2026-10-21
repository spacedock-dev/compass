import { describe, expect, it } from 'vitest';
import type { WorkEntry } from '../intent/work';
import { clock } from '../observed';
import {
  citedLine,
  departureTitle,
  departureWhat,
  indexEntries,
  localRecordedTime,
  verdictLine,
  type Answer,
} from './result';
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

  it('keeps the level word on Nothing found only at None or low', () => {
    expect(
      verdictLine({
        answer: { kind: 'nothing-found' },
        level: 'None or low',
        byId,
        midFlight: false,
      }),
    ).toBe('None or low: Nothing found against what it read.');
  });

  it('never puts Medium or higher on a reading that found nothing against the intent', () => {
    const text = verdictLine({
      answer: { kind: 'nothing-found' },
      level: '',
      heldBack: [],
      byId,
      midFlight: false,
    });
    expect(text).toBe('Nothing found against what it read.');
  });

  it('says in the same sentence why no level is drawn when every line is consistent', () => {
    expect(
      verdictLine({
        answer: { kind: 'nothing-found' },
        level: '',
        heldBack: ['A line of your intent is not shown by any check.'],
        byId,
        midFlight: false,
      }),
    ).toBe(
      'Nothing found against what it read, but no level is drawn: a line of your intent is not shown by any check.',
    );
    expect(
      verdictLine({
        answer: { kind: 'nothing-found' },
        level: '',
        heldBack: [
          'The record contradicts what the agent said.',
          'A later direction of yours is unsettled.',
        ],
        byId,
        midFlight: true,
      }),
    ).toBe(
      'So far: Nothing found against what it read, but no level is drawn: the record contradicts what the agent said; a later direction of yours is unsettled.',
    );
  });

  it('draws no level word on a failed check the reading found, with or without a departure', () => {
    const failed = entry('f', 800, { type: 'tool_report', subject: 'check', result: 'failed' });
    expect(
      verdictLine({
        answer: { kind: 'failed-check', failed },
        level: '',
        byId: indexEntries([failed]),
        midFlight: false,
      }),
    ).toBe(`A check failed at ${clock(800)}.`);
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
  it('never splits an emoji at the cut', () => {
    const summary = `${'x'.repeat(199)}\u{1f600}${'y'.repeat(20)}`;
    const line = citedLine(entry('m', 1, { summary }));
    expect(line).toContain('\u{1f600}…');
    expect(/[\ud800-\udbff](?![\udc00-\udfff])/.test(line)).toBe(false);
  });

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

describe('a departure titled by what happened', () => {
  const write = entry('w', 900, { type: 'tool_report', subject: 'write', summary: 'src/a.ts' });
  const failed = entry('c', 910, {
    type: 'tool_report',
    subject: 'check',
    result: 'failed',
    summary: 'pytest',
  });
  const said = entry('m', 920);

  it('names the kind of thing the cited entry is, never the constraint', () => {
    expect(departureTitle([write])).toBe('It changed src/a.ts');
    expect(departureTitle([failed])).toBe('A check failed');
    expect(departureTitle([said])).toBe('What the agent said departs from this');
    expect(departureTitle([])).toBe('');
  });

  it('prefers a write or a check over a message, which only reports on one', () => {
    expect(departureTitle([said, write])).toBe('It changed src/a.ts');
    expect(departureWhat([said, write])).toContain('src/a.ts');
  });

  it("says what a departure on the reader's own words is, and lets the agent's message beside it title it", () => {
    const you = entry('p', 800, {
      type: 'user_message',
      by: 'person:me',
      summary: 'Ship the queue',
    });
    expect(departureTitle([you])).toBe('Your own words depart from this');
    expect(departureWhat([you])).toBe(`At ${clock(800)} you said “Ship the queue”.`);
    expect(departureTitle([you, said])).toBe('What the agent said departs from this');
    expect(departureWhat([you, said])).toContain('the agent said');
  });

  it('says What as one sentence with the time, ending in a single stop', () => {
    const line = departureWhat([said]);
    expect(line).toBe(`At ${clock(920)} the agent said “Done: the billing rate is now 0.25”.`);
    expect(departureWhat([write])).toBe(`At ${clock(900)} the agent changed src/a.ts.`);
    expect(departureWhat([failed])).toBe(`At ${clock(910)} a check failed: pytest.`);
    expect(departureWhat([])).toBe('');
  });
});

describe('a quote is never cut inside a word', () => {
  it('ends on a whole word before the ellipsis', () => {
    const summary = `${'plain words and nothing else '.repeat(10)}`;
    const line = citedLine(entry('m', 1, { summary }));
    const inner = line.slice('Agent said: “'.length, -2);
    expect(line.endsWith('…”')).toBe(true);
    expect(inner.length).toBeLessThanOrEqual(200);
    expect(
      inner.split(' ').every((word) => ['plain', 'words', 'and', 'nothing', 'else'].includes(word)),
    ).toBe(true);
  });

  it('cuts at the last space even when it falls before the halfway mark', () => {
    const summary = `short ${'x'.repeat(300)}`;
    expect(citedLine(entry('m', 1, { summary }))).toBe('Agent said: “short…”');
  });
});
