import type { Meta, StoryObj } from '@storybook/react-vite';
import { seeInContext } from './citation';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { useEffect, useState } from 'react';
import { App } from '../src/App';
import { LIVE_HINT } from '../src/drift/sentences';
import { DRIFT_SUBTITLE, INTENT_MEASURED } from '../src/intent/sentences';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { WHAT_IT_DID_PLACEHOLDER } from '../src/sessions/WhatItDid';
import { createShell } from '../src/shell/createShell';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';
import { routeOf } from './drift.scenario';

/* The session page as one column (owner, 2026-10-19): the header, the answer block when the session needs
   input, the Intent card, the What the session has done card, the Drift card and Full activity, collapsed.
   Every story mounts the real page over a scripted backend; a path nobody scripted answers `{}`. */

const meta = { title: 'Sessions/One-column page' } satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

const G = 1900000000;

const message = (n: number) => ({
  fact_id: `e${String(n)}`,
  at: G - 100 + n,
  type: 'agent_message',
  by: 'agent',
  source_session: { harness: 'claude', sid: 's1' },
  summary: `Synthetic entry ${String(n)}`,
  evidence: { source: 'transcript', confidence: 'exact' },
  ordinal: n,
});

/* A stored reading whose Goal cites what `cites` names: `e5` sits on the older record page, `ghost` on none. */
const reading = (cites: readonly string[], readAt: number, windowStart: number) => ({
  revision_read: 1,
  revision_read_at: G - 190,
  window_start: windowStart,
  read_at: readAt,
  evidence_through: G - 10,
  goal_source: 'typed',
  scope: 'last-turn',
  scope_text: 'Read up to its last turn.',
  stamp: 'model · m',
  cutoff: 'Evidence read to its end.',
  coverage: {
    tail_truncated: false,
    tail_start: null,
    unlisted: 0,
    unread_checks: 0,
    goal_source: 'typed',
  },
  criteria: {
    goal: {
      result: 'consistent with the evidence read',
      cites,
      detail: '',
      clause: 'Synthetic goal',
    },
  },
});

const ASK = {
  id: 'q1',
  session_id: 's1',
  harness: 'claude',
  question: 'Run the synthetic migration now?',
  options: ['Yes, run it', 'Not yet'],
  age_sec: 30,
};

interface Log {
  answers: string[];
  asking: boolean;
  release: (() => void) | null;
  readAt: number;
  served: number;
  stallOlder: boolean;
  olderAsked: boolean;
  releaseOlder: (() => void) | null;
}
const log: Log = {
  answers: [],
  asking: false,
  release: null,
  readAt: G - 10,
  served: 0,
  stallOlder: false,
  olderAsked: false,
  releaseOlder: null,
};

/* `windowStart` is the session's current intent window; the stored reading keeps its own, so a later window
   makes it a retained reading whose citations may sit before the one now open. `stallOlder` holds the older
   record page until the story releases it. */
function PageExample({
  asking = false,
  cites = null,
  windowStart = G - 200,
  stallOlder = false,
  ended = false,
  readingWindow = G - 200,
}: {
  readonly asking?: boolean;
  readonly cites?: readonly string[] | null;
  readonly windowStart?: number;
  readonly stallOlder?: boolean;
  readonly ended?: boolean;
  readonly readingWindow?: number;
}) {
  const [shell] = useState(() => {
    log.answers = [];
    log.asking = asking;
    log.release = null;
    log.readAt = G - 10;
    log.served = 0;
    log.stallOlder = stallOlder;
    log.olderAsked = false;
    log.releaseOlder = null;
    const history = fakeRouterEnvironment('#n=session:demo:claude:s1');
    let generation = G;
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
    return createShell({
      env: createFakeEnvironment({ clock: createFakeClock() }),
      router: createRouter(history.env),
      provider: () => fakeBackend(),
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
      fetch: async (url, init) => {
        if (url.startsWith('/api/data')) {
          log.served += 1;
          return json({
            generated: generation++,
            annotate: true,
            annotate_cap: 240,
            reading_check: 'passed',
            reading: {
              consent: true,
              off: false,
              providers: { claude: true },
              words: { claude: true },
              tool_output: { claude: ['api'] },
              used: 1,
              limit: 10,
            },
            reading_routes: {
              claude: routeOf('claude', {
                provider: 'claude',
                label: 'Claude Code',
                reason: 'own-harness',
                note: "This session's own harness reads it.",
                fallback: false,
              }),
            },
            ...(log.asking ? { ask: true, asks: [ASK] } : {}),
            sessions: [
              {
                harness: 'claude',
                sid: 's1',
                project: 'demo',
                project_key: '/demo',
                title: 'Synthetic layout session',
                state: log.asking ? 'needs_input' : 'working',
                started_at: G - 3600,
                tasks: [{ subject: 'running Bash', status: 'in_progress' }],
                state_detail: 'running Bash',
                turn: { elapsed_h: '3m' },
                delegated_launches: 2,
                delegated_unpaired: 1,
                delegated_visibility: 'full',
                delegated_latest_launch_at: G - 300,
                // Quiet for 50 minutes with a launch unpaired, so the "still running?" check is drawn.
                delegated_quiet_since: G - 3000,
                ...(ended ? { ended_at: G - 60 } : {}),
                reading_eligibility: { ok: true, reason: null, until: null, sentence: null },
                annotation_goal: 'Synthetic goal',
                annotation_revision: 1,
                annotation_revision_count: 1,
                annotation_at: G - 200,
                annotation_goal_saved_at: G - 200,
                annotation_window_start: windowStart,
                annotation_binding_why: 'These words are bound to claude:s1.',
                ...(cites
                  ? {
                      annotation_reading_count: 1,
                      annotation_assessment: reading(cites, log.readAt, readingWindow),
                    }
                  : {}),
              },
            ],
          });
        }
        if (url === '/api/answer') {
          log.answers.push(String(init?.body));
          await new Promise<void>((resolve) => {
            log.release = resolve;
          });
          log.asking = false;
          return json({ answered: true });
        }
        if (url.startsWith('/api/project-context'))
          return json({ semantic: { facts: [] }, sources: { work: { tool_reports: [] } } });
        if (url.startsWith('/api/annotations'))
          return json({ annotations: [], intent_revision: 'r1' });
        if (url.startsWith('/api/session-record')) {
          const older = url.includes('before=');
          if (older && log.stallOlder) {
            log.olderAsked = true;
            await new Promise<void>((resolve) => {
              log.releaseOlder = resolve;
            });
          }
          return json({
            state: 'ok',
            session: { harness: 'claude', sid: 's1' },
            entries: Array.from({ length: 50 }, (_, i) => message((older ? 50 : 100) - i)),
            next: older ? null : 'older',
            reached_start: older,
            bound: null,
            scanned_bytes: 65536,
            kinds: ['user_message', 'agent_message'],
          });
        }
        return json({});
      },
    });
  });
  useEffect(
    () => () => {
      shell.runtime.dispose();
      shell.display.dispose();
    },
    [shell],
  );
  return (
    <>
      <App shell={shell} />
      <button type="button" onClick={() => void shell.runtime.refresh()}>
        Simulate board poll
      </button>
    </>
  );
}

const ORDER = ['Asked you', 'Intent', 'Drift', 'What the session has done', 'Full activity'];

/* The page's own regions, by role and accessible name, in document order. */
function regions(root: HTMLElement): HTMLElement[] {
  return within(root)
    .getAllByRole('region')
    .filter((node) => ORDER.includes(node.getAttribute('aria-label') ?? labelOf(node)));
}
function labelOf(node: HTMLElement): string {
  const id = node.getAttribute('aria-labelledby');
  return id ? (document.getElementById(id)?.textContent ?? '').trim() : '';
}
const named = (root: HTMLElement) =>
  regions(root).map((node) => node.getAttribute('aria-label') ?? labelOf(node));

async function atWidth(width: number, check: () => Promise<void>) {
  const browserPage =
    '__vitest_browser_runner__' in window ? (await import('vitest/browser')).page : null;
  const before = { width: window.innerWidth, height: window.innerHeight };
  if (browserPage) await browserPage.viewport(width, 800);
  try {
    if (browserPage) await expect(window.innerWidth).toBe(width);
    await check();
  } finally {
    if (browserPage) await browserPage.viewport(before.width, before.height);
  }
}

async function inOrderTopToBottom(root: HTMLElement, expected: readonly string[]) {
  await waitFor(() => expect(named(root)).toEqual(expected));
  const title = within(root).getByRole('heading', { level: 1 });
  const nodes = [title, ...regions(root)];
  for (let i = 1; i < nodes.length; i += 1) {
    const above = nodes[i - 1] as HTMLElement;
    const below = nodes[i] as HTMLElement;
    await expect(
      above.compareDocumentPosition(below) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    // One column: each region starts below the one before it, never beside it.
    await expect(below.getBoundingClientRect().top).toBeGreaterThanOrEqual(
      above.getBoundingClientRect().bottom - 1,
    );
  }
  await expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(window.innerWidth);
}

export const RegionsInOrder: Story = {
  render: () => <PageExample />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('heading', { level: 1, name: 'Synthetic layout session' });
    const expected = ['Intent', 'Drift', 'What the session has done', 'Full activity'];
    for (const width of [1280, 400]) {
      await atWidth(width, () => inOrderTopToBottom(canvasElement, expected));
    }
    // The header: the state with its dot, leading the line that says what it is doing.
    const status = canvasElement.querySelector('[data-next-session-status]') as HTMLElement;
    await expect(status).toHaveTextContent('State: working');
    await expect(status.querySelector('[data-next-session-status-dot]')).toBeVisible();
    await expect(status.nextElementSibling).toHaveTextContent(/running Bash · turn started 3m ago/);
    await expect(canvas.getByText(WHAT_IT_DID_PLACEHOLDER)).toBeVisible();
    await expect(canvas.getByRole('button', { name: 'Full activity' })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
  },
};

/* Every control, sentence and limit the retired More held, in its new home, and More gone. */
export const MoreIsRetired: Story = {
  render: () => <PageExample />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('heading', { level: 1, name: 'Synthetic layout session' });
    await expect(canvas.queryByRole('button', { name: 'More' })).toBeNull();
    await expect(canvasElement.querySelector('[data-next-session-more]')).toBeNull();
    const [intent, drift] = await waitFor(() => {
      const found = regions(canvasElement);
      const pick = (name: string) =>
        found.find((node) => (node.getAttribute('aria-label') ?? labelOf(node)) === name);
      const both = [pick('Intent'), pick('Drift')];
      if (!both[0] || !both[1]) throw new Error('cards not drawn yet');
      return both as [HTMLElement, HTMLElement];
    });
    /* The card's own row keeps the reading start; Clear, the measured sentence, About these saved words,
       Discard everything and Later directions sit behind one quiet menu, which floats inside the page. */
    await expect(within(intent).getByRole('button', { name: /^Saved · reads from/ })).toBeVisible();
    await expect(within(intent).queryByRole('button', { name: 'Clear' })).toBeNull();
    await userEvent.click(within(intent).getByRole('button', { name: 'More about these words' }));
    const inIntent = within(canvasElement);
    await waitFor(async () =>
      expect(await inIntent.findByRole('button', { name: 'Clear' })).toBeVisible(),
    );
    await expect(inIntent.getByText(INTENT_MEASURED)).toBeVisible();
    await expect(inIntent.getByRole('button', { name: 'About these saved words' })).toBeVisible();
    // The offer's summary; the press it opens is the second control of that name.
    await expect(
      inIntent.getAllByRole('button', { name: 'Discard everything' })[0],
    ).toHaveAttribute('aria-expanded', 'false');
    await expect(inIntent.getByRole('button', { name: /^Later directions: / })).toBeVisible();
    await expect(
      inIntent.getByRole('button', { name: 'How Intent and drift works' }),
    ).toBeVisible();
    // Behind their summaries: the saved stamp's definition and binding key, the binding sentence, and the
    // limit under Later directions.
    await userEvent.click(within(intent).getByRole('button', { name: /^Saved · reads from/ }));
    await waitFor(() => expect(inIntent.getByText('Each save is a revision.')).toBeVisible());
    await expect(intent.querySelector('.next-cockpit-held-bound')).toHaveTextContent(/s1/);
    // Pressing the stamp moves focus out of the menu, which closes it; the menu opens again for the rest.
    const more = within(intent).getByRole('button', { name: 'More about these words' });
    if (more.getAttribute('aria-expanded') !== 'true') await userEvent.click(more);
    await userEvent.click(await inIntent.findByRole('button', { name: 'About these saved words' }));
    await waitFor(() =>
      expect(inIntent.getByText('These words are bound to claude:s1.')).toBeVisible(),
    );
    await userEvent.click(inIntent.getByRole('button', { name: /^Later directions: / }));
    await waitFor(() =>
      expect(inIntent.getByText(/^Nothing here decides whether it changes/)).toBeVisible(),
    );
    const inDrift = within(drift);
    const head = drift.querySelector('header') as HTMLElement;
    await expect(within(head).getByRole('switch', { name: 'Live monitor' })).toBeVisible();
    await expect(within(head).getByText(DRIFT_SUBTITLE)).toBeVisible();
    await expect(within(head).getByText(LIVE_HINT)).toBeVisible();
    // What the monitor does is the switch's own helper text.
    await expect(
      within(head).getByRole('switch', { name: 'Live monitor' }),
    ).toHaveAccessibleDescription(LIVE_HINT);
    await expect(inDrift.getByText(/^Delegated work: 2 recorded launches/)).toBeVisible();
    await expect(
      inDrift.getByText(/^Is the work this session launched still running\?/),
    ).toBeVisible();
    await expect(inDrift.getByRole('button', { name: 'Analyze drift' })).toBeVisible();
    // Pause model calls stands in the card's head in every state, and beside what it stops in What is sent.
    await expect(within(head).getByRole('button', { name: 'Pause model calls' })).toBeVisible();
    await userEvent.click(inDrift.getByRole('button', { name: 'What is sent' }));
    const off = await waitFor(() => {
      const found = within(document.body)
        .getAllByRole('button', { name: 'Pause model calls' })
        .find((node) => node.closest('[data-slot="popover-content"]'));
      expect(found).toBeDefined();
      return found as HTMLElement;
    });
    await waitFor(() => expect(off).toBeVisible());
    await userEvent.keyboard('{Escape}');
  },
};

/* An ended session: the note that nothing is promised to read what is saved sits in About these saved words. */
export const MoreIsRetiredForAnEndedSession: Story = {
  render: () => <PageExample ended />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('heading', { level: 1, name: 'Synthetic layout session' });
    await userEvent.click(await canvas.findByRole('button', { name: 'More about these words' }));
    const about = await canvas.findByRole('button', { name: 'About these saved words' });
    await userEvent.click(about);
    await waitFor(() =>
      expect(
        canvas.getByText(
          'This session has ended. Anything you save against it is kept, and nothing is promised to read it.',
        ),
      ).toBeVisible(),
    );
  },
};

function spyScroll() {
  const calls: (ScrollIntoViewOptions | boolean | undefined)[] = [];
  const original = Element.prototype.scrollIntoView;
  const media = window.matchMedia;
  Element.prototype.scrollIntoView = function scroll(options) {
    calls.push(options);
    original.call(this, options);
  };
  window.matchMedia = (query: string) =>
    ({ ...media.call(window, query), matches: query.includes('reduce') }) as MediaQueryList;
  return {
    calls,
    restore: () => {
      Element.prototype.scrollIntoView = original;
      window.matchMedia = media;
    },
  };
}

/* The Goal cites an entry on the older record page. The press opens Full activity, reads that page, and lands
   on the entry with its tint; Escape goes back to the press, and neither move animates under reduced motion. */
export const CitationLoadsAnOlderEntry: Story = {
  render: () => <PageExample cites={['e5']} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const scroll = spyScroll();
    try {
      const jump = () =>
        canvas.getByRole('button', {
          name: 'Load the cited entries in Full activity for Goal: Synthetic goal',
        });
      await waitFor(() => expect(jump()).toBeVisible());
      await waitFor(() =>
        expect(canvasElement.querySelectorAll('[data-next-entry-id]')).toHaveLength(50),
      );
      await expect(canvasElement.querySelector('[data-next-entry-id="e5"]')).toBeNull();
      const trigger = canvas.getByRole('button', { name: 'Full activity' });
      await expect(trigger).toHaveAttribute('aria-expanded', 'false');
      await userEvent.click(jump());
      await expect(trigger).toHaveAttribute('aria-expanded', 'true');
      const row = await waitFor(() => {
        const found = canvasElement.querySelector<HTMLElement>('[data-next-entry-id="e5"]');
        if (!found) throw new Error('the older page has not arrived');
        return found;
      });
      await waitFor(() => expect(document.activeElement).toBe(row));
      await expect(row).toHaveAttribute('data-next-cited');
      await expect(getComputedStyle(row).backgroundColor).not.toBe('rgba(0, 0, 0, 0)');
      // Full activity eases open; the row is there at once and in view once it has.
      await waitFor(() => expect(row).toBeVisible());
      const box = row.getBoundingClientRect();
      await expect(box.bottom).toBeGreaterThan(0);
      await expect(box.top).toBeLessThan(window.innerHeight);
      await expect(scroll.calls.at(-1)).toEqual({ behavior: 'instant', block: 'center' });
      /* Once the entry is held, the finding names it by its number instead of offering to load it, and the
         way back lands on that number. */
      const cited = () =>
        canvas.getByRole('link', {
          name: /^Show #\d+(\.\d+)? in Full activity for Goal: Synthetic goal$/,
        });
      await userEvent.keyboard('{Escape}');
      await expect(document.activeElement).toBe(cited());
      await expect(scroll.calls.at(-1)).toEqual({ behavior: 'instant', block: 'center' });
      // The visible way back does the same.
      await seeInContext(cited());
      await waitFor(() => expect(document.activeElement).toBe(row));
      await userEvent.click(within(row).getByRole('button', { name: 'Back to the finding' }));
      await expect(document.activeElement).toBe(cited());
    } finally {
      scroll.restore();
    }
  },
};

/* The Goal cites an entry no record page returns. The press reads to the record's start, then says so where it
   would have landed, and focus goes there rather than staying on a control whose answer is elsewhere. */
export const CitationThatCannotLoadSaysSo: Story = {
  render: () => <PageExample cites={['ghost']} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const jump = () =>
      canvas.getByRole('button', {
        name: 'Load the cited entries in Full activity for Goal: Synthetic goal',
      });
    await waitFor(() => expect(jump()).toBeVisible());
    await userEvent.click(jump());
    const note = await waitFor(() => {
      const found = canvasElement.querySelector<HTMLElement>('[data-next-jump-missing]');
      if (!found) throw new Error('the read has not finished');
      return found;
    });
    await expect(note).toHaveTextContent(
      'An entry this finding cites could not be loaded: the record read for this session does not list it.',
    );
    await expect(note).toHaveAttribute('role', 'status');
    await waitFor(() => expect(document.activeElement).toBe(note));
    await expect(canvasElement.querySelectorAll('[data-next-entry-id]')).toHaveLength(100);
    await userEvent.click(within(note).getByRole('button', { name: 'Back to the finding' }));
    await expect(document.activeElement).toBe(jump());
    // Escape on the way back, too, returns to the finding rather than leaving the session page.
    await userEvent.click(jump());
    // The press takes the old sentence down and draws its own.
    const again = await waitFor(() => {
      const found = canvasElement.querySelector<HTMLElement>('[data-next-jump-missing]');
      if (!found || document.activeElement !== found) throw new Error('not landed yet');
      return found;
    });
    within(again).getByRole('button', { name: 'Back to the finding' }).focus();
    await userEvent.keyboard('{Escape}');
    await expect(document.activeElement).toBe(jump());
    await expect(
      canvas.getByRole('heading', { level: 1, name: 'Synthetic layout session' }),
    ).toBeVisible();
  },
};

/* A retained reading: the intent was saved again with a later window, and the Goal cites `e5`, from before
   that window and on the older record page. The first page already reaches past the window, so Show more says
   nothing about older entries, yet the press still reads the older page and lands on the entry. */
export const RetainedReadingCitesBeforeTheWindow: Story = {
  render: () => <PageExample cites={['e5']} windowStart={G - 30} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() =>
      expect(canvasElement.querySelectorAll('[data-next-entry-id]').length).toBeGreaterThan(0),
    );
    const jump = await canvas.findByRole('button', {
      name: 'Load the cited entries in Full activity for Goal: Synthetic goal',
    });
    await expect(canvasElement.querySelector('[data-next-unloaded]')).toBeNull();
    await expect(canvasElement.querySelector('[data-next-entry-id="e5"]')).toBeNull();
    await userEvent.click(jump);
    const row = await waitFor(() => {
      const found = canvasElement.querySelector<HTMLElement>('[data-next-entry-id="e5"]');
      if (!found) throw new Error('the older page has not arrived');
      return found;
    });
    await waitFor(() => expect(document.activeElement).toBe(row));
    await expect(row).toHaveAttribute('data-next-cited');
  },
};

/* The Goal cites `e5`, on the older page and from before the window the reading itself read. The press loads it,
   but the reading's own rules set it aside, so no row is marked: the sentence says so and takes focus. */
export const CitationSetAsideByTheReadingSaysSo: Story = {
  render: () => <PageExample cites={['e5']} readingWindow={G - 60} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      await canvas.findByRole('button', {
        name: 'Load the cited entries in Full activity for Goal: Synthetic goal',
      }),
    );
    const note = await waitFor(() => {
      const found = canvasElement.querySelector<HTMLElement>('[data-next-jump-missing]');
      if (!found) throw new Error('the read has not finished');
      return found;
    });
    await expect(note).toHaveTextContent(
      /^The entries this finding cites are loaded, but none is marked/,
    );
    await waitFor(() => expect(document.activeElement).toBe(note));
    await expect(canvasElement.querySelector('[data-next-entry-id="e5"]')).not.toBeNull();
    await expect(canvasElement.querySelector('[data-next-cited]')).toBeNull();
  },
};

async function pollWithNewReading(canvasElement: HTMLElement) {
  const before = log.served;
  log.readAt = G - 5;
  await userEvent.click(within(canvasElement).getByRole('button', { name: 'Simulate board poll' }));
  await waitFor(() => expect(log.served).toBeGreaterThan(before));
}

/* The press's older page is slow, and a new reading arrives while it is read. When the page finally answers,
   the press it served belongs to a reading that is gone, so no "could not be loaded" sentence appears. */
export const SlowReadEndsAfterANewReading: Story = {
  render: () => <PageExample cites={['ghost']} stallOlder />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const jump = await canvas.findByRole('button', {
      name: 'Load the cited entries in Full activity for Goal: Synthetic goal',
    });
    await userEvent.click(jump);
    await waitFor(() => expect(log.releaseOlder).not.toBeNull());
    await pollWithNewReading(canvasElement);
    log.releaseOlder?.();
    await waitFor(() =>
      expect(canvasElement.querySelectorAll('[data-next-entry-id]')).toHaveLength(100),
    );
    // Long enough for the ended read's settle to have drawn the sentence, were it going to.
    await new Promise((resolve) => setTimeout(resolve, 150));
    await expect(canvasElement.querySelector('[data-next-jump-missing]')).toBeNull();
  },
};

/* The sentence stands, then a new reading arrives: the sentence and the press it answered go with the old
   reading, and the control it kept drawn goes too, since the record has been read to its start. */
export const NoteLeavesWithItsReading: Story = {
  render: () => <PageExample cites={['ghost']} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const name = 'Load the cited entries in Full activity for Goal: Synthetic goal';
    await userEvent.click(await canvas.findByRole('button', { name }));
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-next-jump-missing]')).not.toBeNull(),
    );
    await pollWithNewReading(canvasElement);
    await waitFor(() => expect(canvasElement.querySelector('[data-next-jump-missing]')).toBeNull());
    await expect(canvas.queryByRole('button', { name })).toBeNull();
  },
};

/* A question arrives while the page is open: it leads the page, one press sends the exact request and option,
   and a second press while that one is pending sends nothing. */
export const QuestionLeadsAndAnswersOnce: Story = {
  render: () => <PageExample />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('heading', { level: 1, name: 'Synthetic layout session' });
    await waitFor(() =>
      expect(named(canvasElement)).toEqual([
        'Intent',
        'Drift',
        'What the session has done',
        'Full activity',
      ]),
    );
    log.asking = true;
    await userEvent.click(canvas.getByRole('button', { name: 'Simulate board poll' }));
    await inOrderTopToBottom(canvasElement, ORDER);
    const asked = regions(canvasElement)[0] as HTMLElement;
    await expect(asked).toHaveTextContent('Run the synthetic migration now?');
    const yes = within(asked).getByRole('button', { name: 'Yes, run it' });
    await userEvent.click(yes);
    await waitFor(() => expect(log.answers).toHaveLength(1));
    await expect(JSON.parse(log.answers[0] ?? '{}')).toEqual({ id: 'q1', index: 0 });
    await waitFor(() => expect(yes).toHaveAttribute('aria-busy', 'true'));
    await userEvent.click(yes);
    await userEvent.click(within(asked).getByRole('button', { name: 'Not yet' }));
    await expect(log.answers).toHaveLength(1);
    log.release?.();
    await waitFor(() => expect(named(canvasElement)[0]).toBe('Intent'));
    await expect(log.answers).toHaveLength(1);
  },
};
