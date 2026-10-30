import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import '../src/drift/drift.css';
import { Meter, Scale } from '../src/drift/DriftLevelView';
import { LEVEL_SCALE } from '../src/drift/sentences';
import {
  analysisRow,
  DriftScenario,
  fact,
  failedCheck,
  JOB,
  passedCheck,
  STORED_READING,
  written,
  type Scenario,
} from './drift.scenario';
import {
  auditContrast,
  clippedControls,
  contrastOf,
  formatFailures,
  grayOf,
  hasFocusRing,
  overflowReport,
  restingRing,
  rgbOf,
  settled,
} from './a11y.audit';

/* The accessibility pass, held by measurement. Contrast is audited on every story by `vitest.setup.ts`, so every
   state any story draws is held to 4.5:1 (3:1 for large text) without a list here to forget a state from. What
   is here is what a per-story audit cannot say: that the audit can fail, that a level reads without colour,
   that the pages fit the narrow widths a reader zooms into, and that the session page's controls take focus in
   a sensible order with a ring.

   Literal browser zoom is not scriptable in this runner. A 1280 px window at 200% zoom lays out at 640 CSS px
   (the layout viewport shrinks by the zoom factor), so "1280 at 200%" is measured as a 640 px viewport. Device
   pixel ratio is not changed: it alters image density and not layout. 375 and 320 are measured at their own
   width and at 188 and 160, their 200% equivalents. */

const meta = {
  title: 'Accessibility',
  component: DriftScenario,
  parameters: { layout: 'fullscreen' },
} satisfies Meta<typeof DriftScenario>;
export default meta;
type Story = StoryObj<typeof meta>;

export const TheAuditFailsBelowTheThreshold: Story = {
  args: { scenario: {} },
  render: () => (
    <div data-a11y-fixture style={{ background: '#222', padding: 8 }}>
      <p style={{ color: '#eee', margin: 0 }}>Plenty of contrast here</p>
      <p style={{ color: '#555', margin: 0 }}>Too little contrast here</p>
      <p style={{ color: '#777', margin: 0, fontSize: 30 }}>Large text needs only three</p>
      <div style={{ filter: 'grayscale(1)', background: '#222' }}>
        <p style={{ color: '#e4886a', margin: 0 }}>Grey keeps its luminance</p>
        <p style={{ color: '#3b3b3b', margin: 0 }}>Grey that is too dark</p>
      </div>
      <p style={{ color: '#eee', margin: 0, opacity: 0.3 }}>Faded text counts as faded</p>
    </div>
  ),
  play: async ({ canvasElement }) => {
    // The page-wide audit leaves a fixture alone; this one measures it on purpose.
    const fixture = canvasElement.querySelector('[data-a11y-fixture]') as HTMLElement;
    fixture.removeAttribute('data-a11y-fixture');
    const report = auditContrast(canvasElement);
    fixture.setAttribute('data-a11y-fixture', '');
    const failed = report.failures.map((m) => m.text).sort();
    await expect(failed).toEqual([
      'Faded text counts as faded',
      'Grey that is too dark',
      'Too little contrast here',
    ]);
    await expect(report.lowest?.text).toBe('Grey that is too dark');
    await expect(formatFailures(report)).toContain('Too little contrast here');
  },
};

const LEVELS = ['none_or_low', 'medium', 'high', 'extreme'] as const;

/* Colour alone must not carry the level. Each level is a word, a count of filled segments, and a bold word on
   the scale; and with every colour taken out, a filled segment still stands off an empty one by 3:1 (WCAG
   1.4.11), so the count itself reads in grey. */
export const EveryLevelReadsWithoutColour: Story = {
  args: { scenario: {} },
  render: () => (
    <div
      style={{
        background: 'var(--card, #24231b)',
        padding: 16,
        display: 'grid',
        gap: 16,
        width: 360,
      }}
    >
      {LEVELS.map((level) => (
        <div key={level} data-level-block={level} style={{ filter: 'grayscale(1)' }}>
          <Meter level={level} />
          <Scale level={level} />
        </div>
      ))}
    </div>
  ),
  play: async ({ canvasElement }) => {
    const filled: number[] = [];
    for (const [index, level] of LEVELS.entries()) {
      const block = canvasElement.querySelector<HTMLElement>(`[data-level-block="${level}"]`);
      const segments = [...(block?.querySelectorAll<HTMLElement>('.next-session-drift-seg') ?? [])];
      const on = segments.filter((segment) => segment.hasAttribute('data-on'));
      const off = segments.filter((segment) => !segment.hasAttribute('data-on'));
      filled.push(on.length);
      await expect(on).toHaveLength(index + 1);
      await expect(segments).toHaveLength(4);
      const current = block?.querySelector<HTMLElement>('[data-current]');
      await expect(current?.textContent).toBeTruthy();
      await expect(
        Number(getComputedStyle(current as HTMLElement).fontWeight),
      ).toBeGreaterThanOrEqual(600);
      const body = [...(block?.querySelectorAll('.next-session-drift-scale > span') ?? [])];
      await expect(body.indexOf(current as Element)).toBe(LEVEL_SCALE.indexOf(level));
      if (off.length) {
        const grey = (node: HTMLElement) =>
          grayOf(rgbOf(getComputedStyle(node).backgroundColor), 1);
        const ratio = contrastOf(grey(on[0] as HTMLElement), grey(off[0] as HTMLElement));
        await expect(
          ratio,
          `${level}: filled against empty segment in grey`,
        ).toBeGreaterThanOrEqual(3);
      }
    }
    await expect(filled).toEqual([1, 2, 3, 4]);
    await expect(auditContrast(canvasElement).failures).toEqual([]);
  },
};

const FAILED = [failedCheck('c1', 500)];
const WRITES = [
  written('w1', 220, 'src/queue/worker.ts'),
  written('w2', 240, 'src/queue/index.ts'),
  written('w3', 260, 'tests/test_queue.py'),
];
const RESULT: Scenario = {
  session: STORED_READING,
  facts: [...WRITES, ...FAILED, passedCheck('c2', 600)],
  work: { analysis_levels: [analysisRow('claude')] },
};
const PAGES: Record<string, Scenario> = {
  'Session result': RESULT,
  Sessions: { ...RESULT, initialView: 'sessions' },
  Attention: { ...RESULT, initialView: 'attention' },
  Projects: { ...RESULT, initialView: 'projects' },
};

/* The page waits for a region that proves it drew its state before a measure is taken. */
const READY: Record<string, string> = {
  'Session result': '[data-next-result]',
  Sessions: 'article.next-operation-row, main',
  Attention: 'main',
  Projects: 'main',
};

type Viewport = (width: number, height: number) => Promise<void>;
async function viewportOf(): Promise<{ set: Viewport; restore: () => Promise<void> }> {
  const driver =
    '__vitest_browser_runner__' in window ? (await import('vitest/browser')).page : null;
  const before = { width: window.innerWidth, height: window.innerHeight };
  return {
    set: async (width, height) => {
      if (driver) await driver.viewport(width, height);
    },
    restore: async () => {
      if (driver) await driver.viewport(before.width, before.height);
    },
  };
}

function fitsAt(name: string, width: number): Story {
  return {
    args: { scenario: PAGES[name] as Scenario },
    play: async ({ canvasElement }) => {
      const { set, restore } = await viewportOf();
      try {
        await set(width, 800);
        await waitFor(
          () => expect(canvasElement.querySelector(READY[name] as string)).not.toBeNull(),
          {
            timeout: 5000,
          },
        );
        await within(canvasElement).findAllByRole('button');
        const page = overflowReport();
        await expect(window.innerWidth, 'the viewport took the width').toBe(width);
        await expect(page.wide, `${name} at ${width}px: controls outside the viewport`).toEqual([]);
        await expect(
          page.page,
          `${name} at ${width}px: the page scrolls sideways (${page.page} > ${page.client})`,
        ).toBeLessThanOrEqual(page.client);
        await expect(
          clippedControls(canvasElement),
          `${name} at ${width}px: clipped controls`,
        ).toEqual([]);
      } finally {
        await restore();
      }
    },
  };
}

export const SessionResultAt375: Story = fitsAt('Session result', 375);
export const SessionResultAt320: Story = fitsAt('Session result', 320);
export const SessionResultAt188: Story = fitsAt('Session result', 188);
export const SessionResultAt160: Story = fitsAt('Session result', 160);
export const SessionResultAt1280Zoomed200: Story = fitsAt('Session result', 640);
export const SessionsAt375: Story = fitsAt('Sessions', 375);
export const SessionsAt320: Story = fitsAt('Sessions', 320);
export const SessionsAt188: Story = fitsAt('Sessions', 188);
export const SessionsAt160: Story = fitsAt('Sessions', 160);
export const SessionsAt1280Zoomed200: Story = fitsAt('Sessions', 640);
export const AttentionAt375: Story = fitsAt('Attention', 375);
export const AttentionAt320: Story = fitsAt('Attention', 320);
export const AttentionAt188: Story = fitsAt('Attention', 188);
export const AttentionAt160: Story = fitsAt('Attention', 160);
export const AttentionAt1280Zoomed200: Story = fitsAt('Attention', 640);
export const ProjectsAt375: Story = fitsAt('Projects', 375);
export const ProjectsAt320: Story = fitsAt('Projects', 320);
export const ProjectsAt188: Story = fitsAt('Projects', 188);
export const ProjectsAt160: Story = fitsAt('Projects', 160);
export const ProjectsAt1280Zoomed200: Story = fitsAt('Projects', 640);

const FOCUSABLE =
  'a[href], button, input, select, textarea, summary, [tabindex]:not([tabindex="-1"])';

const tabber = async () =>
  '__vitest_browser_runner__' in window ? (await import('vitest/browser')).userEvent : null;

const reachable = (canvasElement: HTMLElement): HTMLElement[] =>
  [...canvasElement.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
    (control) =>
      !control.matches(':disabled') &&
      control.checkVisibility({ visibilityProperty: true }) &&
      control.getBoundingClientRect().width > 0 &&
      !control.closest('[inert]'),
  );

/* Presses Tab from the start of the page, and returns what took focus in order. Each ring is a change the focus
   made to the control's own resting style, so a shadow it wears all the time does not pass as one. */
async function tabThrough(
  canvasElement: HTMLElement,
  controls: HTMLElement[],
): Promise<HTMLElement[]> {
  const driver = await tabber();
  if (!driver) return [];
  const resting = new Map(controls.map((control) => [control, restingRing(control)]));
  (document.activeElement as HTMLElement | null)?.blur();
  const visited: HTMLElement[] = [];
  for (let press = 0; press < controls.length + 6; press += 1) {
    await driver.tab();
    const now = document.activeElement as HTMLElement;
    if (!canvasElement.contains(now) || visited.includes(now)) break;
    visited.push(now);
    await expect(
      hasFocusRing(now, resting.get(now) ?? restingRing(now)),
      `no focus ring on ${now.outerHTML.slice(0, 80)}`,
    ).toBe(true);
  }
  return visited;
}

/* Every control the page offers takes focus from Tab, in the order the page reads, with a ring, and nothing
   inert takes it. */
async function everyControlTakesFocus(canvasElement: HTMLElement, ready: string): Promise<void> {
  if (!(await tabber())) return;
  await waitFor(() => expect(canvasElement.querySelector(ready)).not.toBeNull(), {
    timeout: 5000,
  });
  await within(canvasElement).findAllByRole('button');
  await settled();
  const controls = reachable(canvasElement);
  await expect(controls.length).toBeGreaterThan(5);
  const visited = await tabThrough(canvasElement, controls);
  await expect(visited.length, 'Tab moved focus through the page').toBeGreaterThan(5);
  const missed = controls.filter((control) => !visited.includes(control));
  await expect(
    missed.map((control) => control.outerHTML.slice(0, 80)),
    'controls Tab never reached',
  ).toEqual([]);
  await expect(
    visited.filter((control) => control.closest('[inert]')).length,
    'Tab entered an inert block',
  ).toBe(0);
  const places = visited.map((control) => controls.indexOf(control));
  await expect(places, 'Tab follows the order the page reads').toEqual(
    [...places].sort((a, b) => a - b),
  );
}

export const EveryControlTakesFocusInReadingOrderWithARing: Story = {
  args: { scenario: RESULT },
  play: ({ canvasElement }) => everyControlTakesFocus(canvasElement, '[data-next-result]'),
};

/* A re-run in progress dims the old result and makes it inert; the controls outside it stay reachable. */
export const FocusWhileAnalyzing: Story = {
  args: {
    scenario: { ...RESULT, payload: { reading_jobs: { 'claude:s1': JOB } } },
  },
  play: async ({ canvasElement }) => {
    await everyControlTakesFocus(canvasElement, '[data-next-result-dimmed]');
    await expect(canvasElement.querySelector('[data-next-result-dimmed]')).toHaveAttribute('inert');
  },
};

export const FocusOnAStaleResult: Story = {
  args: {
    scenario: {
      ...RESULT,
      facts: [
        ...WRITES,
        ...FAILED,
        passedCheck('c2', 600),
        passedCheck('c3', 1200),
        fact('m1', 1250, { type: 'agent_message', by: 'agent' }),
      ],
    },
  },
  play: ({ canvasElement }) =>
    everyControlTakesFocus(canvasElement, '[data-next-result-stale="work"]'),
};

/* Steer back opens its box with focus inside it, and Tab from there reaches Copy with a ring. */
export const FocusInTheSteerBackBox: Story = {
  args: {
    scenario: {
      ...RESULT,
      clipboard: true,
      correction: {
        ok: true,
        parts: ['Back to my goal: Ship the queue\nPlease continue from here.'],
      },
    },
  },
  play: async ({ canvasElement }) => {
    const driver = await tabber();
    if (!driver) return;
    const card = await within(canvasElement).findByRole('region', { name: 'Drift' });
    await userEvent.click(await within(card).findByRole('button', { name: 'Steer back' }));
    const copy = await within(card).findByRole('button', { name: 'Copy correction' });
    await settled();
    const box = copy.closest('[data-next-steer-section], section') ?? card;
    await expect(box.contains(document.activeElement), 'focus moved into the box').toBe(true);
    const resting = restingRing(copy);
    let reached = document.activeElement === copy;
    for (let press = 0; press < 6 && !reached; press += 1) {
      await driver.tab();
      reached = document.activeElement === copy;
    }
    await expect(reached, 'Tab reaches Copy correction').toBe(true);
    await expect(hasFocusRing(copy, resting), 'Copy correction shows a ring').toBe(true);
  },
};
