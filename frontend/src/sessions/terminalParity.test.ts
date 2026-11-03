// @vitest-environment node
/* The terminal's `--sessions` and `--sessions waiting` against the board. The recorded payload and the
   expected file are read by this test and by `tests/test_terminal_sessions.py`, so the two readers are held
   to one answer: this file proves the board gives it, that one proves the terminal does. */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { attentionModel } from '../attention/model';
import { riskSubject } from '../attention/subjects';
import { resumeCommand } from '../controls/resumeCommand';
import { observe, sessionKey, type Row } from '../observed';
import { asPayload } from '../observed/values';
import { buildSessionsScreen, rowState } from './rows';

const read = (path: string): unknown =>
  JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'));

const fixture = read('../../test/fixtures/client-contract/data-session-states.json') as {
  response: { body: Row };
};
const expected = read('../../test/fixtures/session-groups.json') as Record<string, unknown>;

const keyOf = (row: Row): [string, string] => [String(row['harness']), String(row['sid'])];

/* What a reader of the board is told, per row, in the board's own words. */
function boardView(payload: Row) {
  const model = observe(payload);
  const screen = buildSessionsScreen(payload, model);
  const rows = (list: typeof screen.active) =>
    list.map((row) => ({
      key: keyOf(row.session),
      state: rowState(row.session),
      outcome: row.session.outcomeKnown ? row.session.outcomeText : null,
      git: row.session.outcomeKnown ? row.session.gitText : null,
      command: resumeCommand(row.session.harness, String(row.session.resume_id ?? '')),
      ended: row.endedSince,
      drift: row.drift ? row.drift.age : null,
    }));
  const attention = attentionModel(payload);
  const drawn = new Set(
    [...model.risks, ...model.boardRisks].map((risk) => riskSubject(risk, attention)?.key),
  );
  const waiting = attention.needs
    .filter((subject) => !drawnAsRiskRow(subject, drawn))
    .map((subject) => {
      const row = subject.session;
      return row ? keyOf(row) : ['ask', String(subject.asks[0]?.['id'])];
    });
  const unreported = model.coverage.rows
    .filter((row) => !row.blockKnown)
    .map((row) => `${row.label}: ${row.blockText}`);
  return {
    active: rows(screen.active),
    history: rows(screen.history),
    waiting,
    coverage: model.coverage.gates,
    unreported,
  };
}

/* An ownerless request is drawn as a board risk row on the Attention screen; the terminal still lists it,
   because it waits on the reader. Only a session a risk row already draws is left out. */
function drawnAsRiskRow(subject: { key: string; session: Row | null }, drawn: Set<unknown>) {
  return subject.session !== null && drawn.has(subject.key);
}

describe('the board against the terminal listing', () => {
  const payload = asPayload(fixture.response.body);

  it('holds the sessions the terminal lists, in its groups, and in the same words', () => {
    expect(boardView(payload)).toEqual(expected['board']);
  });

  it('keys every row by the identity the file names', () => {
    const keys = payload['sessions'] as Row[];
    expect(keys.map(sessionKey).length).toBe(keys.length);
  });
});
