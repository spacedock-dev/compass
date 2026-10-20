import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { useEffect, useState } from 'react';
import { App } from '../src/App';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { SAMPLE_FIXTURE, type SampleFixture, SampleFixtureContext } from '../src/sample/fixture';
import { SAMPLE_FRAGMENT } from '../src/sample/ids';
import { TOUR } from '../src/sample/tour';
import { createShell } from '../src/shell/createShell';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';

/* The sample session as a new reader meets it, in real Chromium: the numbered (i) marks and their popups,
   the stored summary and its departure marks, the tinted cited entries, the held controls and the stored
   correction. What is asserted is hover, layout and colour, which the jsdom tests cannot see. The page around
   it polls a board of its own that has nothing in it, because the sample draws from its own data and never
   from that board. */

const meta = { title: 'Sample session/Page' } satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

type Json = Record<string, unknown>;

function SampleExample({ fragment }: { readonly fragment: string }) {
  const [shell] = useState(() => {
    const history = fakeRouterEnvironment(fragment);
    return createShell({
      env: createFakeEnvironment({ clock: createFakeClock() }),
      router: createRouter(history.env),
      provider: () => fakeBackend(),
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
      fetch: (url) =>
        Promise.resolve(
          new Response(JSON.stringify(url.startsWith('/api/data') ? { sessions: [] } : {}), {
            status: 200,
          }),
        ),
    });
  });
  useEffect(
    () => () => {
      shell.runtime.dispose();
      shell.display.dispose();
    },
    [shell],
  );
  return <App shell={shell} />;
}

function WithFixture({ fixture }: { readonly fixture: SampleFixture }) {
  return (
    <SampleFixtureContext value={fixture}>
      <SampleExample fragment={SAMPLE_FRAGMENT} />
    </SampleFixtureContext>
  );
}

const marks = (root: HTMLElement) => [...root.querySelectorAll<HTMLElement>('[data-sample-mark]')];
const loaded = async (root: HTMLElement) => {
  await waitFor(
    () => expect(root.querySelectorAll('[data-next-entry-id]').length).toBeGreaterThan(10),
    { timeout: 10000 },
  );
  await waitFor(() => expect(root.querySelector('[data-next-summary]')).not.toBeNull(), {
    timeout: 10000,
  });
};
const settle = () =>
  new Promise<void>((resolve) =>
    requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
  );
const HELD = 'View only: this sample cannot be edited, saved or run.';

/* The stored summary as the fixture carries it, so a story can name a citation by where it stands. */
const SUMMARY = (SAMPLE_FIXTURE.context['sources'] as Json)['summary'] as {
  readonly blocks: readonly {
    readonly phases: readonly { readonly bullets: readonly { readonly cites: string[] }[] }[];
  }[];
};
function cited(block: number, phase: number, bullet: number, which: 'first' | 'last'): string {
  const cites = SUMMARY.blocks[block]?.phases[phase]?.bullets[bullet]?.cites ?? [];
  return (which === 'first' ? cites[0] : cites[cites.length - 1]) ?? '';
}

export const MarksTeachThePage: Story = {
  render: () => <SampleExample fragment={SAMPLE_FRAGMENT} />,
  play: async ({ canvasElement }) => {
    await loaded(canvasElement);
    await expect(canvasElement.querySelector('[data-sample-banner]')).toHaveTextContent(
      'Sample session (view only)',
    );
    await expect(marks(canvasElement)).toHaveLength(TOUR.length);
    // A mark draws small, but its press target reaches well past the drawn circle (a padded hit area),
    // so a point eight pixels above it still lands on it.
    const summary = canvasElement.querySelector('[data-sample-mark="summary"]') as HTMLElement;
    summary.scrollIntoView({ block: 'center', behavior: 'instant' });
    await settle();
    const box = summary.getBoundingClientRect();
    await expect(document.elementFromPoint(box.left + box.width / 2, box.top - 8)).toBe(summary);
  },
};

/* The marks follow their parts down the one-column page, so the numbers read in order from the top: the
   tour's order is the page's. Full activity's mark sits beside its trigger, in view while it is collapsed. */
export const MarksFollowThePage: Story = {
  render: () => <SampleExample fragment={SAMPLE_FRAGMENT} />,
  play: async ({ canvasElement }) => {
    await loaded(canvasElement);
    await expect(marks(canvasElement).map((mark) => mark.getAttribute('data-sample-mark'))).toEqual(
      TOUR.map((note) => note.id),
    );
    const activity = canvasElement.querySelector('[data-sample-mark="activity"]') as HTMLElement;
    await expect(activity).toBeVisible();
    await expect(
      within(canvasElement).getByRole('button', { name: 'Full activity' }),
    ).toHaveAttribute('aria-expanded', 'false');
  },
};

/* One story per tour note: its mark sits inside the part it explains, and hovering it opens its words. */
const PARTS: Readonly<Record<string, string>> = {
  intent: '[aria-labelledby="next-session-intent-heading"]',
  summary: '[data-next-session-summary]',
  phase: '[data-next-summary-marked]',
  departure: '[data-next-departure="goal"]',
  steer: '[data-next-result-primary]',
  sent: '[data-next-session-drift]',
  activity: '[data-next-session-full-activity]',
};
function markExplains(id: string): Story {
  const note = TOUR.find((each) => each.id === id);
  return {
    render: () => <SampleExample fragment={SAMPLE_FRAGMENT} />,
    play: async ({ canvasElement }) => {
      await loaded(canvasElement);
      const mark = canvasElement.querySelector(`[data-sample-mark="${id}"]`) as HTMLElement;
      await expect(mark.closest(PARTS[id] ?? '?')).not.toBeNull();
      mark.scrollIntoView({ block: 'center', behavior: 'instant' });
      await settle();
      await userEvent.hover(mark);
      await waitFor(() => {
        const popup = [...document.querySelectorAll('[data-slot="popover-content"]')].find(
          (node) => node.hasAttribute('data-open') && node.textContent?.includes(note?.body ?? '?'),
        );
        expect(popup).toBeDefined();
      });
      await userEvent.unhover(mark);
    },
  };
}
export const MarkIntent = markExplains('intent');
export const MarkSummary = markExplains('summary');
export const MarkPhaseHoldingADeparture = markExplains('phase');
export const MarkDeparture = markExplains('departure');
export const MarkSteerBack = markExplains('steer');
export const MarkWhatIsSent = markExplains('sent');
export const MarkFullActivity = markExplains('activity');

/* The stored summary is drawn as it came back: at least four phases, a phase that holds a departure links to
   its card, and a withheld line says where it stood. */
export const SummaryHoldsADeparture: Story = {
  render: () => <SampleExample fragment={SAMPLE_FRAGMENT} />,
  play: async ({ canvasElement }) => {
    await loaded(canvasElement);
    const summary = canvasElement.querySelector('[data-next-summary]') as HTMLElement;
    await expect(
      summary.querySelectorAll('[data-next-summary-phase]').length,
    ).toBeGreaterThanOrEqual(4);
    await expect(summary.querySelector('[data-next-summary-withheld]')).not.toBeNull();
    const marked = summary.querySelector('[data-next-summary-marked]') as HTMLElement;
    const jump = within(marked).getByRole('button', { name: 'Departure · Goal, go to the card' });
    await userEvent.click(jump);
    await waitFor(() =>
      expect(document.activeElement?.closest('[data-next-departure="goal"]')).not.toBeNull(),
    );
    await expect(canvasElement.querySelector('[data-sample-held]')?.textContent ?? '').toBe('');
  },
};

export const FindingTintsItsEvidence: Story = {
  render: () => <SampleExample fragment={SAMPLE_FRAGMENT} />,
  play: async ({ canvasElement }) => {
    await loaded(canvasElement);
    await expect(canvasElement.querySelectorAll('[data-next-cited]')).toHaveLength(0);
    const jump = canvasElement.querySelector('[data-next-finding="goal"]') as HTMLElement;
    await userEvent.click(jump);
    await waitFor(() =>
      expect(canvasElement.querySelectorAll('[data-next-cited]').length).toBeGreaterThanOrEqual(2),
    );
    for (const row of canvasElement.querySelectorAll('[data-next-cited]')) {
      await expect(getComputedStyle(row).backgroundColor).not.toBe('rgba(0, 0, 0, 0)');
    }
    await expect(canvasElement.querySelector('[data-sample-held]')?.textContent ?? '').toBe('');
  },
};

export const EditsAreHeldAndSteerBackIsShown: Story = {
  render: () => <SampleExample fragment={SAMPLE_FRAGMENT} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await loaded(canvasElement);
    await userEvent.click(
      [...canvasElement.querySelectorAll('button')].find(
        (button) => button.getAttribute('aria-label')?.startsWith('Remove') === true,
      ) as HTMLElement,
    );
    await expect(canvasElement.querySelector('[data-sample-held]')).toHaveTextContent(HELD);
    await userEvent.click(
      canvasElement.querySelector('[data-next-cockpit-action="steer-back"]') as HTMLElement,
    );
    await waitFor(() => expect(canvas.getByText(/Back to my goal:/)).toBeVisible());
    // The stored correction keeps its times as moments; the reader sees them on their own clock, the
    // clock the departure's cited message is drawn on beside it, with the agent's words quoted.
    const box = [...canvasElement.querySelectorAll('textarea')].find((area) =>
      area.value.startsWith('Back to my goal:'),
    ) as HTMLTextAreaElement;
    await expect(box.value).not.toContain('{{clock:');
    await expect(box.value).toMatch(
      /departed from my goal at (\d{4}-\d\d-\d\d )?\d\d:\d\d, where you said "/,
    );
  },
};

/* The sample shows a finished summary, so most summary controls only appear in another state. Each variant
   below draws the sample in the state that offers one control, and the press is held with its sentence. */
function variant(change: (board: Json, summary: Json) => void): SampleFixture {
  const board = structuredClone(SAMPLE_FIXTURE.board) as Json;
  const context = structuredClone(SAMPLE_FIXTURE.context) as Json;
  const summary = (context['sources'] as Json)['summary'] as Json;
  change(board, summary);
  return { ...SAMPLE_FIXTURE, board, context };
}
const running = {
  id: 'sample-job',
  state: 'running',
  part: 2,
  parts: 3,
  reason: '',
  finished_parts: [1],
  attempts: 1,
  started_at: Number(SAMPLE_FIXTURE.board['generated']) - 20,
  notice: null,
};
const VARIANTS: Readonly<Record<string, SampleFixture>> = {
  shipped: SAMPLE_FIXTURE,
  appended: variant((_board, summary) => {
    summary['out_of_date'] = {
      kind: 'appended',
      reason: null,
      affected_blocks: [],
      new_entries: 3,
      appendable: true,
      action: 'update',
    };
  }),
  changed: variant((_board, summary) => {
    summary['out_of_date'] = {
      kind: 'changed_earlier',
      reason: 'content',
      affected_blocks: [0],
      new_entries: 0,
      appendable: false,
      action: 'summarize_again',
    };
  }),
  running: variant((board, summary) => {
    summary['job'] = running;
    const row = (board['sessions'] as Json[])[0] as Json;
    row['summary'] = { ...(row['summary'] as Json), job: running };
  }),
  summariesOff: variant((board) => {
    board['summaries'] = {
      ...(board['summaries'] as Json),
      consent: false,
      off: true,
      reason: 'summaries-off',
    };
  }),
  paused: variant((board) => {
    board['reading'] = {
      ...(board['reading'] as Json),
      consent: false,
      off: true,
      reason: 'model-calls-paused',
    };
  }),
};
/* `opener` names the disclosure a control sits in (What is sent, on either card), which only reads and stays
   live in the sample. */
function pressIsHeld(fixture: keyof typeof VARIANTS, name: RegExp, opener?: string): Story {
  return {
    render: () => <WithFixture fixture={VARIANTS[fixture] ?? SAMPLE_FIXTURE} />,
    play: async ({ canvasElement }) => {
      await loaded(canvasElement);
      if (opener) {
        const open = within(canvasElement).getByRole('button', { name: opener });
        open.scrollIntoView({ block: 'center', behavior: 'instant' });
        await userEvent.click(open);
        await expect(canvasElement.querySelector('[data-sample-held]')?.textContent ?? '').toBe('');
      }
      const press = await waitFor(
        () => {
          const found = [...canvasElement.ownerDocument.querySelectorAll('button')].find(
            (button) =>
              name.test(button.textContent?.trim() ?? '') &&
              getComputedStyle(button).pointerEvents !== 'none',
          );
          expect(found).toBeDefined();
          return found as HTMLElement;
        },
        { timeout: 10000 },
      );
      press.scrollIntoView({ block: 'center', behavior: 'instant' });
      await settle();
      await userEvent.click(press);
      const status = canvasElement.querySelector('[data-sample-held]') as HTMLElement;
      await expect(status).toHaveTextContent(HELD);
      // Seen where the press was: the sentence once sat in the banner, thousands of pixels above, and
      // then at the foot of the viewport over the Copy button. It is drawn just under the press now.
      const box = status.getBoundingClientRect();
      const pressed = press.getBoundingClientRect();
      await expect(box.top).toBeGreaterThanOrEqual(0);
      await expect(box.bottom).toBeLessThanOrEqual(window.innerHeight);
      await expect(box.top).toBeGreaterThanOrEqual(pressed.bottom);
      await expect(box.top - pressed.bottom).toBeLessThan(16);
      await expect(box.left).toBeGreaterThanOrEqual(0);
      await expect(box.right).toBeLessThanOrEqual(document.documentElement.clientWidth);
      await expect(canvasElement.querySelector('[data-next-summary]')).not.toBeNull();
    },
  };
}
export const DeleteSummaryIsHeld = pressIsHeld('shipped', /^Delete summary$/);
export const TurnOffSummariesIsHeld = pressIsHeld(
  'shipped',
  /^Turn off summaries$/,
  'What is sent to Claude Code',
);
export const PauseModelCallsIsHeld = pressIsHeld('shipped', /^Pause model calls$/, 'What is sent');
export const UpdateSummaryIsHeld = pressIsHeld('appended', /^Update summary$/);
export const SummarizeAgainIsHeld = pressIsHeld('changed', /^Summarize again$/);
export const CancelSummaryIsHeld = pressIsHeld('running', /^Cancel$/);
export const TurnSummariesOnIsHeld = pressIsHeld('summariesOff', /^Turn summaries on$/);
export const ResumeModelCallsIsHeld = pressIsHeld('paused', /^Resume model calls$/, 'What is sent');

/* A press at the foot of the viewport gets its sentence above it: drawn below, it was off screen and lapsed
   unseen. */
export const HeldAtTheFootIsDrawnAboveThePress: Story = {
  render: () => <WithFixture fixture={VARIANTS['shipped'] ?? SAMPLE_FIXTURE} />,
  play: async ({ canvasElement }) => {
    await loaded(canvasElement);
    const press = await waitFor(
      () => {
        const found = [...canvasElement.ownerDocument.querySelectorAll('button')].find(
          (button) =>
            /^Delete summary$/.test(button.textContent?.trim() ?? '') &&
            getComputedStyle(button).pointerEvents !== 'none',
        );
        expect(found).toBeDefined();
        return found as HTMLElement;
      },
      { timeout: 10000 },
    );
    press.scrollIntoView({ block: 'end', behavior: 'instant' });
    await settle();
    const pressed = press.getBoundingClientRect();
    await expect(pressed.bottom + 86).toBeGreaterThan(window.innerHeight);
    await userEvent.click(press);
    const status = canvasElement.querySelector('[data-sample-held]') as HTMLElement;
    await expect(status).toHaveTextContent(HELD);
    const box = status.getBoundingClientRect();
    await expect(box.top).toBeGreaterThanOrEqual(0);
    await expect(box.bottom).toBeLessThanOrEqual(window.innerHeight);
    await expect(box.bottom).toBeLessThanOrEqual(pressed.top);
    await expect(pressed.top - box.bottom).toBeLessThan(16);
  },
};

/* A citation anywhere in the session opens in Full activity. The record arrives in two pages, newest first,
   and the board's context holds only the newest page's messages, so the earliest citation is found only by
   reading the older page, which the sample's server answers from the capture. */
function citationOpens(id: string): Story {
  return {
    render: () => <SampleExample fragment={SAMPLE_FRAGMENT} />,
    play: async ({ canvasElement }) => {
      await loaded(canvasElement);
      const chip = canvasElement.querySelector(
        `[data-next-summary] [data-next-outline-entry="${id}"]`,
      ) as HTMLElement;
      await expect(chip).not.toBeNull();
      chip.scrollIntoView({ block: 'center', behavior: 'instant' });
      await userEvent.click(chip);
      const row = () =>
        canvasElement.querySelector(
          `[data-next-cockpit-work] [data-next-entry-id="${id}"]`,
        ) as HTMLElement | null;
      await waitFor(() => expect(document.activeElement).toBe(row()), { timeout: 10000 });
      await expect(
        within(canvasElement).getByRole('button', { name: 'Full activity' }),
      ).toHaveAttribute('aria-expanded', 'true');
      // Full activity opens with a short height transition, so the row is visible once it settles.
      await waitFor(() => expect(row()).toBeVisible(), { timeout: 5000 });
      await expect(canvasElement.querySelector('[data-next-jump-missing]')).toBeNull();
      await expect(canvasElement.querySelector('[data-sample-held]')?.textContent ?? '').toBe('');
    },
  };
}

/* The person's first message, #1, on the older page; the person asking for the walk, partway through;
   the agent's last reply, #81, on the newest page. */
export const EarlyCitationOpensInFullActivity = citationOpens(cited(0, 0, 0, 'first'));
export const MiddleCitationOpensInFullActivity = citationOpens(cited(0, 1, 0, 'first'));
export const LateCitationOpensInFullActivity = citationOpens(cited(1, 2, 1, 'last'));

/* The shipped reading cites nothing before the newest page, so this variant's goal finding cites the
   person's first message, #1, which only the older page holds. Pressing the finding reads that page and
   lights the row, as it would for a longer session's reading. */
const OLDER_CITE = cited(0, 0, 0, 'first');
const OLDER_FINDING: SampleFixture = (() => {
  const board = structuredClone(SAMPLE_FIXTURE.board) as Json;
  const row = (board['sessions'] as Json[])[0] as Json;
  const criteria = (row['annotation_assessment'] as Json)['criteria'] as Json;
  criteria['goal'] = { ...(criteria['goal'] as Json), cites: [OLDER_CITE] };
  return { ...SAMPLE_FIXTURE, board };
})();

export const FindingCitingTheOlderPageTintsIt: Story = {
  render: () => <WithFixture fixture={OLDER_FINDING} />,
  play: async ({ canvasElement }) => {
    await loaded(canvasElement);
    await expect(
      canvasElement.querySelector(`[data-next-cockpit-work] [data-next-entry-id="${OLDER_CITE}"]`),
    ).toBeNull();
    const press = canvasElement.querySelector('[data-next-finding="goal"]') as HTMLElement;
    press.scrollIntoView({ block: 'center', behavior: 'instant' });
    await userEvent.click(press);
    const row = () =>
      canvasElement.querySelector(
        `[data-next-cockpit-work] [data-next-entry-id="${OLDER_CITE}"][data-next-cited]`,
      ) as HTMLElement | null;
    await waitFor(() => expect(row()).not.toBeNull(), { timeout: 10000 });
    await expect(
      within(canvasElement).getByRole('button', { name: 'Full activity' }),
    ).toHaveAttribute('aria-expanded', 'true');
    await waitFor(() => expect(row()).toBeVisible(), { timeout: 5000 });
    await expect(getComputedStyle(row() as HTMLElement).backgroundColor).not.toBe(
      'rgba(0, 0, 0, 0)',
    );
    await expect(canvasElement.querySelector('[data-next-jump-missing]')).toBeNull();
    await expect(canvasElement.querySelector('[data-sample-held]')?.textContent ?? '').toBe('');
  },
};

export const SessionsInvitesAReader: Story = {
  render: () => <SampleExample fragment="#n=sessions" />,
  play: async ({ canvasElement }) => {
    const link = await within(canvasElement).findByRole('link', {
      name: 'See a sample session (view only)',
    });
    await expect(link).toHaveAttribute('href', SAMPLE_FRAGMENT);
  },
};
