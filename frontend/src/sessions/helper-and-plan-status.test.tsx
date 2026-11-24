import {
  toBeInTheDocument,
  toBeVisible,
  toHaveAttribute,
  toHaveTextContent,
} from '@testing-library/jest-dom/matchers';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { expect, it } from 'vitest';
import { payloadSessionRows } from '../observed';
import { scenarios } from '../project/generate.test.helper';
import { mountProject } from '../project/testing';
import { SubagentsView } from './DetailParts';
import { sessionSubagents } from './detail';

expect.extend({ toBeInTheDocument, toBeVisible, toHaveAttribute, toHaveTextContent });

it('counts the helpers shown and keeps working, inactive and unmeasured helpers distinct', () => {
  const helpers = sessionSubagents(
    [
      { name: 'unmeasured helper' },
      { name: 'inactive helper', active: false },
      { name: 'working helper', active: true },
    ],
    0,
    null,
  );
  if (!helpers) throw new Error('Expected three helpers');
  const { container } = render(<SubagentsView subagents={helpers} />);
  expect.soft(screen.queryByRole('list', { name: 'Helpers (3)' })).toBeInTheDocument();
  /* Each helper's tile is a named picture of its published state. No harness records a helper's finish, so a
     helper that is not running is State not known, never Ended, and keeps the words that say why. */
  for (const [name, tile, word] of [
    ['unmeasured helper', 'State not known', 'Activity not published'],
    ['inactive helper', 'State not known', 'Not running'],
    ['working helper', 'Working', ''],
  ] as const) {
    const row = screen.getByText(name).closest('[data-next-session-subagent]') as HTMLElement;
    expect.soft(within(row).getByRole('img', { name: tile })).toBeVisible();
    if (word) expect.soft(row).toHaveTextContent(word);
    else expect.soft(row.textContent).toBe(name);
  }
  expect
    .soft(container.querySelectorAll('[data-next-row-tile][data-size="small"]'))
    .toHaveLength(3);
  expect.soft(container.querySelectorAll('[tabindex]')).toHaveLength(0);
});

it('names plan status in words beside decorative icons', async () => {
  const scenario = scenarios()[2];
  if (!scenario) throw new Error('Expected the project plan scenario');
  const project = String(payloadSessionRows(scenario.board)[0]?.['project']);
  const page = mountProject({
    hash: '#n=project:' + encodeURIComponent(project),
    data: scenario.board,
    contexts: scenario.context ? { [project + '\n']: scenario.context } : {},
  });
  await page.settle();
  fireEvent.click(screen.getByText('Show project plan'));
  for (const [id, word] of [
    ['alpha', 'Live'],
    ['beta', 'Pending'],
  ]) {
    const row = document.querySelector(`[data-next-plan-entity="${id}"]`);
    expect.soft(row).toHaveTextContent(word ?? '');
    expect.soft(row?.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
  }
});
