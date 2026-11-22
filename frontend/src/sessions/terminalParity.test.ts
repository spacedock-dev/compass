// @vitest-environment node
/* The terminal's `--sessions` and `--sessions waiting` against the board. The recorded payload and the
   expected file are read by this test and by `tests/test_terminal_sessions.py`, so the two readers are held
   to one answer: this file proves the board gives it, that one proves the terminal does.

   `session-groups.json` is the BOARD's output, committed by hand after reading it. It must never be
   regenerated from the Python port: a file the port wrote would agree with the port by construction. */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { attentionModel } from '../attention/model';
import { riskSubject } from '../attention/subjects';
import { resumeCommand } from '../controls/resumeCommand';
import { observe, sessionKey, type Row } from '../observed';
import { asPayload } from '../observed/values';
import { buildSessionsScreen, rowState } from './rows';
import { groupLabel } from './declared';

const read = (path: string): unknown =>
  JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'));

const fixture = read('../../test/fixtures/client-contract/data-session-states.json') as {
  response: { body: Row };
};
const expected = read('../../test/fixtures/session-groups.json') as Record<string, unknown>;
const finishedRuns = read('../../test/fixtures/finished-run-terminal.json') as {
  name: string;
  payload: Row;
  now: string;
}[];

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

  it('holds the sessions the terminal lists, in its groups, with the board’s evidence-based state wording', () => {
    // 2026-11-22, docs/design-frontend-migration.md#held-to-recorded-answers
    type Board = ReturnType<typeof boardView>;
    type RecordedRow = Omit<Board['active'][number], 'state'> & { state: string };
    const recorded = expected['board'] as Omit<Board, 'active' | 'history'> & {
      active: RecordedRow[];
      history: RecordedRow[];
    };
    // The recorded Idle bucket includes four rows with no observed stop.
    const withoutStop = new Set([
      'claude:f6a7b8c9',
      'claude:d0e1f2a3',
      'codex:019c0000-1111-7222-8333-444455557777',
      'gemini:gem-0001',
    ]);
    const idleOnBoard = (rows: typeof recorded.active) =>
      rows.map((row) =>
        row.state === 'Idle'
          ? { ...row, state: withoutStop.has(row.key.join(':')) ? 'State not published' : 'Quiet' }
          : row,
      );
    expect(boardView(payload)).toEqual({
      ...recorded,
      active: idleOnBoard(recorded.active),
      history: idleOnBoard(recorded.history),
    });
  });

  it.each(finishedRuns)('holds the terminal Now reading: $name', ({ payload, now }) => {
    const screen = buildSessionsScreen(payload, observe(payload));
    expect([...screen.active, ...screen.history].map((row) => row.session.nowWords)).toEqual([now]);
  });

  it('keys every row by the identity the file names', () => {
    const keys = payload['sessions'] as Row[];
    expect(keys.map(sessionKey).length).toBe(keys.length);
  });
});

/* New metadata has its own hand-authored answer; the retired page's golden records stay untouched. */
it('holds the terminal declared-parent and group words together with the board', () => {
  const fixture = read('../../test/fixtures/declared-sessions.json') as {
    payload: Row;
    expected: Record<string, string[]>;
  };
  const screen = buildSessionsScreen(fixture.payload, observe(fixture.payload));
  for (const row of [...screen.active, ...screen.history]) {
    const words = [
      groupLabel(row.source),
      row.relations.parentText,
      row.relations.waitingText,
    ].filter(Boolean);
    expect(words).toEqual(fixture.expected[row.session.sid]);
  }
});
