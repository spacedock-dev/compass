import {
  toBeInTheDocument,
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

expect.extend({ toBeInTheDocument, toHaveAttribute, toHaveTextContent });

it('counts only helpers observed running and keeps inactive and unmeasured helpers distinct', () => {
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
  expect.soft(screen.queryByText('1 RUNNING SUBAGENT')).toBeInTheDocument();
  for (const [name, word] of [
    ['unmeasured helper', 'Activity not published'],
    ['inactive helper', 'Not running'],
  ]) {
    const row = screen.getByText(name ?? '').closest('[data-next-session-subagent]');
    expect.soft(row).toHaveTextContent(word ?? '');
    expect.soft(row?.querySelector('svg')).toBeNull();
  }
  const working = screen.getByText('working helper').parentElement;
  if (!working) throw new Error('Expected a working helper row');
  expect.soft(within(working).queryByRole('img', { name: 'Working' })).toBeInTheDocument();
  expect.soft(container.querySelectorAll('[data-icon="working"]')).toHaveLength(1);
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
