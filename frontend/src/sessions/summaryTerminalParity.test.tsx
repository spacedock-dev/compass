import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';
import { render, screen, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { SummaryPage, grant, script } from '../../stories/summary.scenario';
import { parseFocusedSummary } from '../api/summary';
import fixture from '../sample/session.fixture.json';
import { bulletWords, ledeWords, summaryNotes, withheldSentence, withheldTitle } from './summary';

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
