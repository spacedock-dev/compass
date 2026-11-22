import {
  toBeInTheDocument,
  toHaveAccessibleName,
  toHaveTextContent,
} from '@testing-library/jest-dom/matchers';

expect.extend({ toBeInTheDocument, toHaveAccessibleName, toHaveTextContent });

import { within } from '@testing-library/react';
import { expect, it } from 'vitest';
import declared from '../../test/fixtures/declared-sessions.json';
import { mountSessions } from './testing';

const at = 1_900_000_000;
const evidence = {
  scan: { state: 'idle', acquisition: 'scan-only' },
  idle: { state: 'idle' },
  clean: { state: 'idle', finished_at: at - 100, dirty: false },
  dirty: { state: 'idle', finished_at: at - 100, dirty: true },
  transcript: { state: 'idle', turn_end_at: at - 100, acquisition: 'scan-only' },
  live: { state: 'working', active: true },
  lapsed: { state: 'working', active: false },
  ended: { ended_at: at - 100 },
  'ended-with-request': { state: 'idle', ended_at: at - 100 },
  'dirty-end': { ended_at: at - 100, dirty: true },
  waiting: { state: 'idle' },
  unpublished: {},
};
const data = {
  generated: at,
  ask: true,
  asks: [
    { id: 'held', harness: 'claude', session_id: 'waiting', question: 'Continue?' },
    {
      id: 'ended-request',
      harness: 'claude',
      session_id: 'ended-with-request',
      question: 'Approve the result?',
      options: ['Approve', 'Decline'],
    },
  ],
  sessions: Object.entries(evidence).map(([sid, fields]) => ({
    sid,
    title: sid,
    project: 'demo',
    harness: 'claude',
    ...fields,
  })),
};

function node(selector: string): HTMLElement {
  const element = document.querySelector<HTMLElement>(selector);
  if (!element) throw new Error(`Missing ${selector}`);
  return element;
}

it('draws only the statuses and outcomes that a Sessions row has evidence for', async () => {
  const page = mountSessions({ data });
  await page.settle();
  const row = (id: string) => node(`article[data-next-session="${id}"]`);
  const state = (id: string) => row(id).querySelector('[data-next-row-state]');
  for (const id of ['scan', 'idle', 'unpublished']) {
    expect.soft(row(id).querySelector('svg[data-icon="quiet"]')).toBeNull();
    expect
      .soft(row(id))
      .toHaveTextContent(
        id === 'scan'
          ? 'Read by scanning: no turn end can be observed here'
          : 'State not published',
      );
  }
  for (const id of ['clean', 'dirty', 'transcript']) {
    expect.soft(state(id)).toHaveAccessibleName('Quiet');
    expect.soft(state(id)?.querySelector('[data-icon="quiet"]')).toBeInTheDocument();
    expect.soft(row(id).querySelector('.next-operation-outcome svg')).toBeNull();
  }
  expect.soft(row('clean')).toHaveTextContent('Stop observed; git state clean');
  expect.soft(row('dirty')).toHaveTextContent('Stop observed with uncommitted work');
  expect.soft(row('transcript')).not.toHaveTextContent('no turn end can be observed here');
  expect.soft(state('ended')).toHaveAccessibleName('Ended');
  expect.soft(state('ended')?.querySelector('[data-icon="ended"]')).toBeInTheDocument();
  expect.soft(state('ended-with-request')).toHaveTextContent('Ended');
  expect
    .soft(state('ended-with-request')?.querySelector('[data-icon="ended"]'))
    .toBeInTheDocument();
  expect.soft(row('ended-with-request').querySelector('[data-icon="waiting"]')).toBeNull();
  expect.soft(row('ended-with-request')).toHaveTextContent('Approve the result?');
  expect
    .soft(row('dirty-end').querySelector('.next-operation-outcome [data-icon="worth-a-look"]'))
    .toBeInTheDocument();
  expect.soft(state('waiting')).toHaveAccessibleName('Waiting on you');
  expect.soft(state('waiting')?.querySelector('[data-icon="waiting"]')).toBeInTheDocument();
  for (const id of ['live', 'lapsed']) {
    expect.soft(state(id)).toHaveAccessibleName('Working');
    expect.soft(state(id)?.querySelectorAll('[data-icon="working"]')).toHaveLength(1);
  }
  const pulse = 'motion-safe:animate-status-tile-pulse';
  expect.soft(state('live')?.querySelector('svg')?.classList.contains(pulse)).toBe(true);
  expect.soft(state('lapsed')?.querySelector('svg')?.classList.contains(pulse)).toBe(false);
});

it.each([
  ['scan', 'Read by scanning: no turn end can be observed here'],
  ['idle', 'State not published'],
  ['unpublished', 'State not published'],
  ['ended', 'State: Ended'],
  ['waiting', 'State: Waiting on you'],
  ['clean', 'State: Quiet'],
])('names the observed session header evidence for %s', async (id, sentence) => {
  const page = mountSessions({ data, hash: `#n=session:demo:claude:${id}` });
  await page.settle();
  const header = node('.next-session-detail-header');
  expect(header).toHaveTextContent(sentence);
  if (id === 'scan' || id === 'idle' || id === 'unpublished') {
    expect(header.querySelector('.next-session-state')).toBeNull();
  }
});

it.each([
  ['#n=sessions', 'article[data-next-session=parent]'],
  ['#n=project:demo', '[data-next-going-on=parent]'],
  ['#n=projects', 'button[data-next-session=parent]'],
])('keeps the declared child wait as text on %s', async (hash, selector) => {
  const page = mountSessions({ hash, data: declared.payload });
  await page.settle();
  const parent = node(selector);
  expect.soft(parent).toHaveTextContent('Waiting on child "Check build"');
  expect.soft(parent.querySelector('[data-icon=working]')).toBeNull();
  expect.soft(within(parent).queryByRole('img', { name: 'Working' })).toBeNull();
});

it('uses the same child wait when a project is scoped to that parent', async () => {
  const page = mountSessions({
    hash: '#n=project:demo:claude%3Aparent',
    data: declared.payload,
  });
  await page.settle();
  const viewing = node('[data-next-cockpit-viewing-session]');
  expect.soft(viewing).not.toHaveTextContent(/working/i);
  expect.soft(viewing).toHaveTextContent('Waiting on child "Check build"');
});
