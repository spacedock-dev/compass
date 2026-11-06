// @vitest-environment node
/* The server's `sources.work.drift_views` against the page, on the real server's bytes. The two files are one
   recorded exchange (`scripts/regen_client_fixtures.py`, scenario `drift_view_scenario`): the board with a stored
   reading, and that session's focused context. The page derives the Drift card from the row and the context, and
   the field the server attached must say what it says. `terminalParity.test.ts` holds the same derivation to a
   corpus; this holds the ATTACHED field to it, which a module test cannot. */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { DriftCase } from './terminalParity.corpus.test.helper';
import { pageView } from './terminalParity.view.test.helper';

const read = (name: string): { response: { body: Record<string, unknown> } } =>
  JSON.parse(
    readFileSync(
      new URL(`../../test/fixtures/client-contract/${name}.json`, import.meta.url),
      'utf8',
    ),
  );

const data = read('data-focused-drift').response.body;
const context = read('context-focused-drift').response.body;
const sessions = data['sessions'] as Record<string, unknown>[];
const served = (
  (context['sources'] as Record<string, unknown>)['work'] as Record<string, unknown[]>
)['drift_views'] as Record<string, unknown>[];

describe('the drift view the server attached, against the page', () => {
  const session = sessions.find((row) => row['sid'] === 'a1b2c3d4') as Record<string, unknown>;
  const item: DriftCase = { name: 'recorded', rules: [], session, payload: data, context };

  it('is one row for the focused session, on the context and on no board row', () => {
    expect(served).toHaveLength(1);
    expect(sessions.every((row) => !('drift_views' in row))).toBe(true);
  });

  it('is what the page derives from the same row and context', () => {
    expect(served[0]).toEqual(pageView(item));
  });

  it('holds back the departure a later unsettled direction demotes', () => {
    const [view] = served as { lines: { state: string; why: string }[]; departures: string[] }[];
    expect(view?.lines[0]).toMatchObject({ state: 'cant-tell', why: 'baseline-open' });
    expect(view?.departures).toEqual([]);
  });
});
