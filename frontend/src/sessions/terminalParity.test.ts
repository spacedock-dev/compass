// @vitest-environment jsdom
/* The terminal's `--sessions` and `--sessions waiting` against the board. The recorded payload and the
   expected file are read by this test and by `tests/test_terminal_sessions.py`, so the two readers are held
   to one answer: this file proves the board gives it, that one proves the terminal does.

   COMPASS_WRITE_SESSIONS_PARITY=1 pnpm exec vitest run frontend/src/sessions/terminalParity.test.ts
   writes a scratch candidate for session-groups.json from the board. Review it before copying it
   into the fixtures directory. The Python port reads the approved answer. */
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fireEvent, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { attentionModel } from '../attention/model';
import { riskSourceText, subjectSource } from '../attention/text';
import { riskSubject } from '../attention/subjects';
import { resumeCommand } from '../controls/resumeCommand';
import { observe, sessionKey, type Row } from '../observed';
import { asPayload } from '../observed/values';
import { buildSessionsScreen } from './rows';
import { groupLabel } from './declared';
import { mountSessions } from './testing';

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
function boardView(payload: Row, root: HTMLElement, needsYou: HTMLElement) {
  const model = observe(payload);
  const screen = buildSessionsScreen(payload, model);
  const rows = (list: typeof screen.active) =>
    list.map((row) => {
      const rendered = sessionRow(root, row.session.harness, row.session.sid);
      return {
        key: keyOf(row.session),
        state: rendered.querySelector('[data-next-row-state]')?.getAttribute('data-next-row-state'),
        outcome: row.session.outcomeKnown ? row.session.outcomeText : null,
        git: row.session.outcomeKnown ? row.session.gitText : null,
        command: resumeCommand(row.session.harness, String(row.session.resume_id ?? '')),
        ended: row.endedSince,
        drift: rowProgress(rendered),
        absence: rendered.querySelector('[data-next-row-absence]')?.textContent ?? null,
      };
    });
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
  const coverage = needsYou.querySelector('.next-attention-coverage');
  if (!coverage) throw new Error('Needs you coverage was not rendered');
  const unreported = [...coverage.querySelectorAll('[data-next-coverage-harness]')]
    .filter((row) => row.querySelector('[data-known]')?.getAttribute('data-known') === 'false')
    .map(
      (row) =>
        `${row.querySelector('strong')?.textContent}: ${row.lastElementChild?.textContent?.split(' · ')[0]}`,
    );
  return {
    active: rows(screen.active),
    history: rows(screen.history),
    waiting,
    coverage: coverage.querySelector(':scope > p')?.textContent,
    unreported,
  };
}

function sessionRow(root: HTMLElement, harness: string, sid: string) {
  const row = [...root.querySelectorAll<HTMLElement>('article[data-next-session]')].find(
    (node) =>
      node.getAttribute('data-next-harness') === harness &&
      node.getAttribute('data-next-session') === sid,
  );
  if (!row) throw new Error(`Session row not rendered: ${harness}:${sid}`);
  return row;
}

function rowProgress(row: HTMLElement) {
  const pills = row.querySelectorAll('[data-next-drift-pill], .next-session-drift-pill');
  expect(pills.length).toBeLessThanOrEqual(1);
  return pills[0]?.textContent?.trim() ?? null;
}

/* An ownerless request is drawn as a board risk row on the Attention screen; the terminal still lists it,
   because it waits on the reader. Only a session a risk row already draws is left out. */
function drawnAsRiskRow(subject: { key: string; session: Row | null }, drawn: Set<unknown>) {
  return subject.session !== null && drawn.has(subject.key);
}

describe('the board against the terminal listing', () => {
  const payload = asPayload(fixture.response.body);

  it('holds the sessions, states and visible marks the board shows', async () => {
    const board = mountSessions({ data: payload });
    const needsYou = mountSessions({ hash: '#n=attention', data: payload });
    await board.settle();
    await needsYou.settle();
    fireEvent.click(
      within(needsYou.container).getByRole('button', { name: "What Compass can't see" }),
    );
    const actual = boardView(payload, board.container, needsYou.container);
    if (process.env['COMPASS_WRITE_SESSIONS_PARITY'] === '1') {
      const candidate = join(
        mkdtempSync(join(tmpdir(), 'compass-terminal-sessions-')),
        'session-groups.json',
      );
      writeFileSync(candidate, `${JSON.stringify({ ...expected, board: actual }, null, 2)}\n`);
      console.info(`Sessions candidate: ${candidate}`);
      return;
    }
    expect(actual).toEqual(expected['board']);
  });

  const headings = expected['headings'] as ({ labels: string[] } & Row)[];
  it.each(headings)('names its groups from $labels', async ({ labels, ...window }) => {
    const { window_hours: _hours, ...data } = payload;
    const board = mountSessions({ data: { ...data, ...window } });
    await board.settle();
    const groups = board.container.querySelectorAll(
      '.next-operation-group h2, .next-operation-group h3',
    );
    expect([...groups].map((heading) => heading.textContent)).toEqual(labels);
  });

  const progress = [
    ...(expected['unpublishedProgress'] as Row[]),
    ...(expected['publishedProgress'] as Row[]),
  ] as ({ name: string; mark: string | null; word?: string | null } & Row)[];
  it.each(progress)(
    'shows the reader the available progress: $name',
    async ({ name: _name, mark, word, ...fields }) => {
      const sid = 'f6a7b8c9';
      const sessions = (payload['sessions'] as Row[]).map((row) =>
        row['sid'] === sid ? { ...row, ...fields } : row,
      );
      const board = mountSessions({ data: { ...payload, sessions } });
      await board.settle();
      const row = sessionRow(board.container, String(fields['harness'] ?? 'claude'), sid);
      expect(rowProgress(row)).toBe(mark);
      expect(row.querySelector('[data-next-row-absence]')?.textContent ?? null).toBe(word ?? null);
    },
  );

  it('reads the progress pill independently of the session title', async () => {
    const sid = 'f6a7b8c9';
    const sessions = (payload['sessions'] as Row[]).map((row) =>
      row['sid'] === sid ? { ...row, title: 'Off course recovery notes' } : row,
    );
    const board = mountSessions({ data: { ...payload, sessions } });
    await board.settle();
    expect(board.container.textContent).toContain('Off course recovery notes');
    expect(rowProgress(sessionRow(board.container, 'claude', sid))).toBeNull();
  });

  it.each(finishedRuns)('holds the terminal Now reading: $name', ({ payload, now }) => {
    const screen = buildSessionsScreen(payload, observe(payload));
    expect([...screen.active, ...screen.history].map((row) => row.session.nowWords)).toEqual([now]);
  });

  it('keeps the published wait of an unowned request on the board card', () => {
    const questions = observe(payload).boardRisks.filter((risk) => risk.kind === 'ask');
    expect(
      questions.map((risk) => [risk.identity, riskSourceText(risk).split(' · waiting ')[1]]),
    ).toEqual(expected['unownedWaits']);
  });

  it('keeps the end and waiting states while withholding ages for unusable observations', () => {
    const stamps = [
      [0, 100000],
      [100000, 1e100],
      [100000, 100001],
    ];
    const results = stamps.map(([generated, stamp]) => {
      const data = {
        generated,
        sessions: [
          { harness: 'claude', sid: 'end', project: 'p', ended_at: stamp },
          {
            harness: 'claude',
            sid: 'wait',
            project: 'p',
            state: 'needs_input',
            blocked_since: stamp,
          },
        ],
      };
      const board = buildSessionsScreen(data, observe(data));
      const attention = attentionModel(data);
      return {
        generated,
        stamp,
        ended: board.history.map((row) => [row.session.nowWords, row.endedSince]),
        waiting: attention.needs.map(
          (subject) => subjectSource(subject, attention).split(' · waiting ')[1] ?? null,
        ),
      };
    });
    expect(results).toEqual(expected['unusableAges']);
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
