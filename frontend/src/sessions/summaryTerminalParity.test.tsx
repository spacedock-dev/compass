import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';
import { render, screen, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { SummaryPage, grant, script, storedSummary } from '../../stories/summary.scenario';
import { parseFocusedSummary } from '../api/summary';
import fixture from '../sample/session.fixture.json';
import {
  LEDE_LAST,
  bulletWords,
  ledeWords,
  outOfDateLine,
  reasonSentence,
  summaryNotes,
  summaryStamp,
  unlinkedSentence,
  withheldSentence,
  withheldTitle,
} from './summary';

function terminalText(summary: Record<string, unknown>, labels: Record<string, string> = {}) {
  const result = spawnSync(
    process.platform === 'win32' ? 'python' : 'python3',
    [
      '-c',
      'import json,sys; from compass_runtime.terminal_summary import render; p=json.load(sys.stdin); print("\\n".join(render(p["summary"],p["labels"],page_url="page")))',
    ],
    {
      cwd: resolve(import.meta.dirname, '../../..'),
      env: { ...process.env, PYTHONPATH: 'compass/skills/compass' },
      input: JSON.stringify({ summary, labels }),
      encoding: 'utf8',
    },
  );
  expect(result.status, result.stderr).toBe(0);
  return result.stdout;
}

const reasons = { grant: null, harness: 'claude', largest: null };

it('a person reads the same local summary clock and freshness sentence in a terminal', () => {
  for (const [kind, count] of [
    ['unchanged', 2],
    ['appended', 1],
    ['appended', 2],
    ['changed_earlier', 0],
  ] as const) {
    const raw = storedSummary({
      out_of_date: { kind, action: 'update', new_entries: count, affected_blocks: [] },
    });
    const parsed = parseFocusedSummary({ sources: { summary: raw } })?.summary;
    if (!parsed) throw new Error('summary missing');
    const shown = terminalText(raw);
    expect(shown).toContain(summaryStamp(parsed, false, 'claude-sonnet-5-5'));
    expect(shown).toContain(outOfDateLine(parsed, reasons)?.sentence);
    expect(shown).not.toContain('+00:00');
    if (kind !== 'unchanged') expect(shown).not.toContain('Some message text remains unsummarized');
  }
});

it('a person keeps lowercase mentions after abbreviations in both openings', () => {
  const words =
    'The person asked for tests. Followed instructions, e.g. the person asked for tests.';
  const shown = terminalText(storedSummary({ lede: { text: words, cites: [] } }));
  expect(shown).toContain(ledeWords(words));
  expect(shown).not.toContain('e.g. You');
});

it.each([0, 1, 3])(
  'a person reads the same explanation for %i unavailable checks and files',
  async (count) => {
    const checks = Array.from({ length: count }, (_, index) => `earlier-check-${String(index)}`);
    const raw = storedSummary({
      lede: { text: 'Opening.', cites: ['older-message', ...checks] },
      blocks: [
        {
          first: 'older-message',
          last: 'older-message',
          entries: 1,
          fingerprint: '0'.repeat(32),
          phases: [
            {
              title: 'Reading',
              bullets: [
                { text: 'Asked for tests.', kind: 'asked', cites: ['older-message'] },
                { text: 'Read checks.', kind: 'did', cites: [...checks, ...checks] },
              ],
            },
          ],
        },
      ],
    });
    const shown = terminalText(raw);
    render(<SummaryPage summary={raw} />);
    const region = await screen.findByRole('region', { name: 'Summary' });
    if (count) {
      expect(shown).toContain(unlinkedSentence(count));
      expect(within(region).getByText(unlinkedSentence(count))).toBeVisible();
    } else {
      expect(shown).not.toContain('cannot be opened from here');
      expect(region.textContent).not.toContain('cannot be opened from here');
    }
    expect(shown).not.toContain('no available label');
  },
);

it.each([
  ['stopped', 'complete'],
  ['bytes', 'complete'],
  ['ceiling', 'complete'],
  ['refused', 'complete'],
  ['no_valid_reply', 'complete'],
  [null, 'complete'],
  ['stopped', 'running'],
  ['stopped', 'stopping'],
] as const)('a person reads the same absent opening reason %s while %s', async (reason, state) => {
  const raw = storedSummary({ lede: null, lede_reason: reason, job: { id: 'job', state } });
  const expected =
    state === 'running' || state === 'stopping'
      ? LEDE_LAST
      : reason
        ? `No opening summary: ${reasonSentence(reason, reasons)}`
        : 'No opening summary.';
  const shown = terminalText(raw);
  expect(shown.split('\n')).toContain(expected);
  expect(shown).not.toContain('No opening summary. (');
  render(<SummaryPage summary={raw} />);
  const region = await screen.findByRole('region', { name: 'Summary' });
  expect(within(region).getByText(expected)).toBeVisible();
});

it('a person reads the recorded session with the page’s speakers, withheld text and citation labels', () => {
  const raw = fixture.context.sources.summary;
  const labels = Object.fromEntries(
    [...fixture.context.semantic.facts, ...fixture.record.entries].flatMap((fact) => {
      const row = fact as Record<string, unknown>;
      return typeof row['ordinal'] === 'number'
        ? [
            [
              row['fact_id'],
              `${String(row['ordinal'])}${typeof row['ordinal_sub'] === 'number' ? `.${String(row['ordinal_sub'])}` : ''}`,
            ],
          ]
        : [];
    }),
  );
  const result = spawnSync(
    process.platform === 'win32' ? 'python' : 'python3',
    [
      '-c',
      'import json,sys; from compass_runtime.terminal_summary import render; p=json.load(sys.stdin); print("\\n".join(render(p["summary"],p["labels"],page_url="page")))',
    ],
    {
      cwd: resolve(import.meta.dirname, '../../..'),
      env: { ...process.env, PYTHONPATH: 'compass/skills/compass' },
      input: JSON.stringify({ summary: raw, labels }),
      encoding: 'utf8',
    },
  );
  expect(result.status, result.stderr).toBe(0);
  const shown = result.stdout;
  const parsed = parseFocusedSummary(fixture.context)?.summary;
  expect(parsed).toBeTruthy();
  if (!parsed) throw new Error('recorded summary missing');
  let position = -1;
  for (const block of parsed.blocks) {
    for (const phase of block.phases) {
      const title = 'text' in phase.title ? phase.title.text : withheldTitle(phase.title.withheld);
      const next = shown.indexOf(title, position + 1);
      expect(next).toBeGreaterThan(position);
      position = next;
      if (phase.bulletsCut)
        expect(shown).toContain(
          `${String(phase.bulletsCut)} more ${phase.bulletsCut === 1 ? 'line was' : 'lines were'} cut from this phase.`,
        );
      for (const bullet of phase.bullets) {
        const words =
          'text' in bullet.text
            ? bulletWords(bullet.kind, bullet.text.text)
            : withheldSentence(bullet.text.withheld);
        expect(shown).toContain(words);
        for (const id of bullet.cites) if (labels[id]) expect(shown).toContain(`[#${labels[id]}]`);
      }
    }
  }
  if (parsed.lede && 'text' in parsed.lede) expect(shown).toContain(ledeWords(parsed.lede.text));
  for (const note of summaryNotes(parsed, '')) expect(shown).toContain(note);
});

beforeEach(() => vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true));

it('a person turning summaries off in a terminal sees machine-wide off on the page without a new summary', async () => {
  const receipt = grant({ consent: false, off: true, reason: 'summaries-off' });
  render(<SummaryPage grant={receipt} summary={fixture.context.sources.summary} />);
  const region = await screen.findByRole('region', { name: 'What the session has done' });
  await within(region).findByText(
    'Summaries are turned off for every session. Nothing is sent for a summary until you turn them on.',
  );
  expect(script.posts).toEqual([]);
});
